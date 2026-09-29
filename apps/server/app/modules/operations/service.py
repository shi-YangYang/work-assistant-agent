from datetime import date
from app.core.digests import digest
from app.core.errors import problem
from app.core.versions import version
from app.db.base import now
from app.modules.operations.models import BusinessAction
from app.modules.operations.receipts import action_dto
from app.modules.operations.mutations.report_completion import submit_action
from app.modules.operations.policy.rules import CONFIRM
from app.modules.operations.targets import preview, source_check
from app.modules.operations.mutations.writes import remove_record as writes_remove_record
from app.modules.reports.models import ReportObligation
from app.modules.reports.service import edit_report as writes_edit_report, ensure_report
from app.modules.team.sources import canonical_token as business_canonical_token
from app.modules.work.service import save_work as writes_save_work
from app.security.access import resolve as business_resolve
from app.security.locks import company_lock as business_company_lock
from app.security.ownership import owned


async def perform(db, actor, row, job=None, *, confirmed=False):
    p = row.params
    if row.action in ('create_work', 'update_work'):
        links = []
        if p['sourceTokens'] and actor.role != 'admin':
            problem(403, '当前账号不能建立团队督办关联')
        for raw in p['sourceTokens']:
            token = business_canonical_token(raw)
            evidence = (job.access if job else row.access).get('reads', {}).get(token)
            if not evidence or evidence.get('type') not in ('work', 'report'):
                problem(403, '督办来源必须来自实际读取的工作或报告')
            await business_resolve(db, actor, evidence, latest=True)
            links.append({'token': token, 'evidence': evidence})
        # Access tracks every source the model saw, including older turns. It
        # must not turn an unrelated personal task into a mandatory follow-up.
        # Explicit links are still verified above and source access is retained.
        from app.modules.operations.mutations.publication import snapshot, selected_attachments
        await selected_attachments(db, actor, p.get('sharedAttachmentIds', []), row.conversation_id)
        publication = snapshot(p['changes'], message_ids=[row.message_id], reference=p.get('deliverableReference'), attachments=p.get('sharedAttachmentIds', []))
        item = await writes_save_work(db, actor, p['changes'], identifier=p['targetId'] if row.action == 'update_work' else None, expected=p['expectedRevision'], sources=[row.message_id], origin='assistant', links=links, access=row.access, publication=publication, revision_origin='assistant_confirmed' if confirmed else 'assistant')
        from app.modules.deliverables.service import link_work
        await link_work(db, actor, p.get('deliverableReference'), row, item)
        row.result = {'objectType': 'work', 'objectId': item.id, 'revision': item.revision, 'changedFields': sorted(p['changes'])}
    elif row.action == 'generate_report':
        if p['kind'] not in ('daily', 'weekly'):
            problem(422, '报告类型无效')
        try:
            day = date.fromisoformat(p['date'])
        except ValueError:
            problem(422, '请明确报告日期')
        timezone = None
        if p['obligationId']:
            obligation = await owned(db, ReportObligation, p['obligationId'], actor, lock=True)
            if obligation.state == 'cancelled':
                problem(409, '汇报安排已撤销')
            if obligation.period != day.isoformat() or obligation.kind != p['kind']:
                problem(409, '报告周期与汇报待办不一致')
            timezone = obligation.timezone
        # Pass the authenticated request through the asynchronous handoff, not
        # a brief invented by the tool-calling model.
        from app.agent.context.conversation_context import request_text
        from app.modules.messages.models import Message
        message = await owned(db, Message, row.message_id, actor)
        instructions = request_text(message, job) if job else message.text
        from app.agent.context.report_context import capture_brief
        source = await capture_brief(db, actor, message, job) if job else None
        item, report_job = await ensure_report(db, actor, p['kind'], day, report_timezone=timezone, instructions=instructions, instruction_source=source)
        if job:
            from app.security.access import inherit
            inherit(actor, report_job, job)
        row.result = {'objectType': 'report', 'objectId': item.id, 'revision': item.revision, 'jobId': report_job.id, 'submitAfter': p['submitAfter']}
        row.state = 'running'
        if report_job.state == 'succeeded':
            from app.modules.operations.mutations.report_completion import complete_action
            await complete_action(db, actor, row)
        return
    elif row.action == 'edit_report':
        item = await writes_edit_report(db, actor, p['targetId'], p['expectedRevision'], p['changes'])
        row.result = {'objectType': 'report', 'objectId': item.id, 'revision': item.revision}
    elif row.action == 'submit_report':
        await submit_action(db, actor, row)
        return
    else:
        kind = 'work' if row.action == 'delete_work' else 'report'
        if job:
            from app.modules.operations.targets import read_target
            from app.modules.operations.mutations.writes import deletion_impact
            target = await read_target(db, actor, row.action, p['targetId'])
            impact = await deletion_impact(db, target, actor)
            removed_ids = {target.id, *impact.get('messageIds', []), *impact.get('attachmentIds', [])}
            # Consuming an authorized deletion receipt removes only the inputs
            # it deletes. Other readers are still invalidated normally.
            job.access = {**job.access, 'reads': {key: value for key, value in job.access.get('reads', {}).items() if value.get('id') not in removed_ids}}
        item = await writes_remove_record(db, actor, kind, p['targetId'], p['expectedRevision'], executing_job=job if job and job.state == 'running' else None)
        row.result = {'objectType': kind, 'objectId': item.id, 'revision': item.revision}
    row.state = 'succeeded'
    # Receipts retain references, never a second copy of deleted/private text.
    row.params = {}
    row.updated_at = now()


async def confirm(db, actor, identifier, expected, *, cancel=False):
    await business_company_lock(db, actor.company_id)
    row = await owned(db, BusinessAction, identifier, actor, lock=True)
    if row.state in ('succeeded', 'running', 'cancelled'):
        return await action_dto(db, actor, row)
    version(row, expected)
    if cancel:
        row.state, row.params, row.result = 'cancelled', {}, {}
        row.revision += 1
        return await action_dto(db, actor, row)
    if row.state != 'pending':
        problem(409, '此操作当前不能确认')
    from app.tasks.runtime.conversation_activity import active_job
    active = await active_job(db, actor, row.conversation_id)
    if active and active.target_id != row.message_id:
        problem(409, '当前会话正在处理后续请求，请完成后再确认', 'conversation_busy')
    await source_check(db, actor, row)
    value = await preview(db, actor, row)
    if digest(value) != row.result.get('previewDigest'):
        problem(409, '内容或删除范围已变化，请重新提出操作')
    from app.tasks.models import Job
    from sqlalchemy import select
    source_job = await db.scalar(select(Job).where(Job.target_id == row.message_id, Job.kind == 'message').order_by(Job.created_at.desc()).limit(1))
    await perform(db, actor, row, source_job, confirmed=True)
    row.revision += 1
    await db.flush()
    return await action_dto(db, actor, row)
