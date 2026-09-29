from fastapi import HTTPException
from app.core.digests import digest
from app.core.errors import problem
from app.modules.operations.models import BusinessAction
from app.modules.operations.policy.rules import LABELS
from app.modules.operations.targets import preview, source_check
from app.modules.reports.models import Report
from app.modules.work.models import WorkItem, WorkRevision
from app.security.access import require as business_require, valid as business_valid
from app.security.ownership import owned
from app.tasks.models import Job
from app.tasks.serializers import job_dto
from sqlalchemy import select


async def refresh_generation(db, actor, row):
    if row.action != 'generate_report' or row.state != 'running':
        return
    report = await owned(db, Report, row.result['objectId'], actor)
    job = await owned(db, Job, row.result['jobId'], actor)
    if job.state == 'succeeded':
        row.state = 'succeeded'
        row.result = {**row.result, 'revision': report.revision}
        if job.phase == 'empty':
            row.result = {**row.result, 'message': '本期没有已确认工作，已准备报告草稿；可在报告页填写。'}
        if row.result.get('submitAfter'):
            if not any(str(v).strip() for v in report.content.values()):
                row.result = {**row.result, 'message': '报告还没有内容，请先填写后再提交。'}
            elif report.candidate:
                row.result = {**row.result, 'message': '新生成内容已保留为候选，请在报告页审阅采用后再提出提交。'}
            else:
                row.action = 'submit_report'
                row.continuation = {}
                row.params = {**row.params, 'targetId': report.id, 'expectedRevision': report.revision}
                value = await preview(db, actor, row)
                row.result = {**row.result, 'previewDigest': digest(value)}
                row.state = 'pending'
        if row.state == 'succeeded':
            row.params = {}
        row.revision += 1
    elif job.state in ('failed', 'awaiting_retry', 'cancelled'):
        # Keep the job reference so the existing report retry UI remains usable.
        row.result = {**row.result, 'message': '报告尚未生成，请打开报告查看原因或重试。'}


async def action_dto(db, actor, row):
    if row.company_id != actor.company_id or row.owner_id != actor.id:
        problem(404, '操作不存在')
    base = {'confirmLabel': '确认' + LABELS[row.action], 'executionMode': row.execution_mode, 'continuation': row.continuation or None, 'id': row.id, 'messageId': row.message_id, 'taskItemId': row.task_item_key, 'action': row.action, 'label': LABELS[row.action], 'state': row.state, 'revision': row.revision, 'createdAt': row.created_at.isoformat()}
    if row.action.startswith('delete_') and row.state == 'succeeded' and row.access.get('role') == actor.role:
        return {**base, 'message': '记录已删除'}
    if row.access.get('role') != actor.role or not await business_valid(db, actor, row.access):
        return {**base, 'state': 'unavailable', 'message': '关联资料已变化或无权查看'}
    try:
        await refresh_generation(db, actor, row)
        base.update(action=row.action, label=LABELS[row.action], confirmLabel='确认' + LABELS[row.action], state=row.state, revision=row.revision)
        if row.state == 'pending':
            await source_check(db, actor, row)
            value = await preview(db, actor, row)
            if digest(value) != row.result.get('previewDigest'):
                problem(409, '内容或删除范围已变化，请重新提出操作')
            return {**base, 'preview': {k: v for k, v in value.items() if k != 'impact'}, 'impact': {k: v for k, v in value.get('impact', {}).items() if k in ('messages', 'attachments')}, 'canConfirm': True}
        if row.state in ('failed', 'conflict', 'cancelled'):
            return {**base, 'message': row.result.get('message', '')}
        kind, identifier = row.result.get('objectType'), row.result.get('objectId')
        if row.action.startswith('delete_') and row.state == 'succeeded':
            return {**base, 'message': '记录已删除'}
        item = await owned(db, WorkItem if kind == 'work' else Report, identifier, actor)
        if kind == 'work':
            await business_require(db, actor, item.access, retained=True)
            revision = await db.scalar(select(WorkRevision).where(WorkRevision.work_id == item.id, WorkRevision.revision == row.result['revision']))
            details = revision.content if revision else {}
            title = details.get('title', item.title)
        else:
            title, details = f'{item.period} {"日报" if item.kind == "daily" else "周报"}', {}
        result = {**base, 'objectType': kind, 'objectId': identifier, 'objectRevision': row.result.get('revision'), 'title': title, 'details': details, 'changedFields': row.result.get('changedFields', []), 'message': row.result.get('message', '')}
        if row.result.get('jobId'):
            job = await owned(db, Job, row.result['jobId'], actor)
            result['job'] = job_dto(job)
        return result
    except HTTPException as error:
        return {**base, 'state': 'conflict' if error.status_code == 409 else 'unavailable', 'message': error.detail['message']}


async def message_actions(db, actor, message):
    if message.owner_id != actor.id:
        return []
    job = await db.scalar(select(Job).where(Job.kind == 'message', Job.target_id == message.id, Job.owner_id == actor.id))
    snapshot = (job.result if job else {}).get('taskSnapshot', {})
    association = BusinessAction.message_id == message.id
    if snapshot.get('relation') == 'continue':
        association = association | (BusinessAction.task_id == snapshot['taskId'])
    rows = (await db.scalars(select(BusinessAction).where(association, BusinessAction.owner_id == actor.id, BusinessAction.company_id == actor.company_id).order_by(BusinessAction.step))).all()
    return [await action_dto(db, actor, row) for row in rows]


def receipt_summary(cards, drafts=()):
    statuses = {'succeeded': '已完成', 'pending': '等待你的确认', 'running': '正在处理', 'cancelled': '已取消', 'failed': '未完成', 'conflict': '内容已变化，未执行', 'unavailable': '当前不可查看'}
    parts = []
    for card in cards:
        state = card['state']
        # Generation keeps its running action so the report can be retried;
        # its terminal child job still determines what the user sees now.
        if state == 'running' and (card.get('job') or {}).get('state') in ('failed', 'awaiting_retry', 'cancelled'):
            state = 'cancelled' if card['job']['state'] == 'cancelled' else 'failed'
        target = f"《{card['title']}》" if card.get('title') else ''
        parts.append(f"{card['label']}{target}：{statuses.get(state, '未完成')}")
    draft_statuses = {'pending': '已保存，等待你的确认', 'confirmed': '已确认', 'ignored': '已忽略'}
    parts.extend(dict.fromkeys(f"{'督办' if draft.business_links else '进展'}建议：{draft_statuses.get(draft.status, '当前不可用')}" for draft in drafts))
    return '；'.join(parts) + '。' if parts else ''


def receipt_reply(review, cards, drafts=(), deliverables=''):
    """Delivered prose plus database-authenticated outcomes."""
    summary = receipt_summary(cards, drafts)
    parts = [review.text] if review.text else [deliverables] if deliverables and review.verified else []
    if summary:
        parts.append(summary)
    if review.verified and review.needs_action:
        parts.append('本次请求仍有操作未完成；已保存的结果会保留。')
    if review.verified and review.needs_response:
        parts.append('所需答复尚未完成核对，暂时无法提供完整结果。')
    if not review.verified:
        parts.append('答复说明暂未完成核对；已保存的操作结果以上方记录为准。' if cards else '答复暂未完成核对，请重试答复核对；业务操作结果会保留。')
    elif review.execution_claims and not cards and not drafts and not deliverables:
        parts.append('本次没有保存新的业务操作结果，未执行创建、修改、提交或删除。')
    elif not parts:
        parts.append('本次暂未交付所需结果，请重试；已保存的操作不会重复执行。')
    return '\n\n'.join(parts)


def current_reply(message, job, cards, drafts):
    """Project the server-owned receipt slot from live state, preserving prose."""
    slot = (job.result or {}).get('replyReceipt') if job else None
    summary = receipt_summary(cards, drafts)
    if slot:
        return slot['prefix'] + summary + slot['suffix']
    # Older receipt-only messages predate the structured slot. Never rewrite
    # arbitrary model prose by searching for status words inside it.
    old_cards = [{**card, 'label': '生成报告', 'state': 'running', 'job': None} if card['action'] in ('generate_report', 'submit_report') else card for card in cards]
    if old_cards and summary and message.reply in (receipt_summary(old_cards), receipt_summary([{key: value for key, value in card.items() if key != 'title'} for card in old_cards])):
        return summary
    if drafts and message.reply == '本次没有保存新的业务操作结果，未执行创建、修改、提交或删除。':
        return summary
    return message.reply
