from datetime import date
from app.core.digests import digest
from app.core.errors import problem
from app.core.versions import version
from app.db.base import now
from app.modules.operations.models import BusinessAction
from app.modules.operations.receipts import action_dto
from app.modules.operations.rules import CONFIRM
from app.modules.operations.targets import preview, source_check
from app.modules.operations.writes import remove_record as writes_remove_record
from app.modules.reports.models import ReportObligation
from app.modules.reports.service import edit_report as writes_edit_report, ensure_report, submit_report as writes_submit_report
from app.modules.team.sources import canonical_token as business_canonical_token
from app.modules.work.service import save_work as writes_save_work
from app.security.access import resolve as business_resolve
from app.security.locks import company_lock as business_company_lock
from app.security.ownership import owned


async def perform(db, actor, row, job=None):
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
        if row.access.get('team') and row.action == 'create_work' and not links:
            problem(422, '团队督办需要明确关联的工作或已提交报告来源')
        item = await writes_save_work(db, actor, p['changes'], identifier=p['targetId'] if row.action == 'update_work' else None, expected=p['expectedRevision'], sources=[row.message_id], origin='assistant', links=links, access=row.access)
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
        item, report_job = await ensure_report(db, actor, p['kind'], day, report_timezone=timezone)
        row.result = {'objectType': 'report', 'objectId': item.id, 'revision': item.revision, 'jobId': report_job.id, 'submitAfter': p['submitAfter']}
        row.state = 'running'
        return
    elif row.action == 'edit_report':
        item = await writes_edit_report(db, actor, p['targetId'], p['expectedRevision'], p['changes'])
        row.result = {'objectType': 'report', 'objectId': item.id, 'revision': item.revision}
    elif row.action == 'submit_report':
        item = await writes_submit_report(db, actor, p['targetId'], p['expectedRevision'])
        row.result = {'objectType': 'report', 'objectId': item.id, 'revision': item.revision}
    else:
        kind = 'work' if row.action == 'delete_work' else 'report'
        item = await writes_remove_record(db, actor, kind, p['targetId'], p['expectedRevision'])
        row.result = {'objectType': kind, 'objectId': item.id, 'revision': item.revision}
    row.state = 'succeeded'
    # Receipts retain references, never a second copy of deleted/private text.
    row.params = {}
    row.updated_at = now()


async def confirm(db, actor, identifier, expected, *, cancel=False):
    await business_company_lock(db, actor.company_id)
    row = await owned(db, BusinessAction, identifier, actor, lock=True)
    if row.state in ('succeeded', 'cancelled'):
        return await action_dto(db, actor, row)
    version(row, expected)
    if cancel:
        row.state, row.params, row.result = 'cancelled', {}, {}
        row.revision += 1
        return await action_dto(db, actor, row)
    if row.state != 'pending' or row.action not in CONFIRM:
        problem(409, '此操作当前不能确认')
    await source_check(db, actor, row)
    value = await preview(db, actor, row)
    if digest(value) != row.result.get('previewDigest'):
        problem(409, '内容或删除范围已变化，请重新提出操作')
    await perform(db, actor, row)
    row.revision += 1
    await db.flush()
    return await action_dto(db, actor, row)
