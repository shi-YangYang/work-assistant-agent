from fastapi import HTTPException
from app.core.digests import digest
from app.core.errors import problem
from app.modules.operations.models import BusinessAction
from app.modules.operations.rules import LABELS
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
    base = {'id': row.id, 'messageId': row.message_id, 'action': row.action, 'label': LABELS[row.action], 'state': row.state, 'revision': row.revision, 'createdAt': row.created_at.isoformat()}
    if row.action.startswith('delete_') and row.state == 'succeeded' and row.access.get('role') == actor.role:
        return {**base, 'message': '记录已删除'}
    if row.access.get('role') != actor.role or not await business_valid(db, actor, row.access):
        return {**base, 'state': 'unavailable', 'message': '关联资料已变化或无权查看'}
    try:
        await refresh_generation(db, actor, row)
        base.update(action=row.action, label=LABELS[row.action], state=row.state, revision=row.revision)
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
    rows = (await db.scalars(select(BusinessAction).where(BusinessAction.message_id == message.id, BusinessAction.owner_id == actor.id).order_by(BusinessAction.step))).all()
    return [await action_dto(db, actor, row) for row in rows]


def receipt_reply(review, cards):
    """Only independently checked prose plus database-authenticated outcomes."""
    statuses = {'succeeded': '已完成', 'pending': '等待你的确认', 'running': '正在处理', 'cancelled': '已取消', 'failed': '未完成', 'conflict': '内容已变化，未执行', 'unavailable': '当前不可查看'}
    summary = '；'.join(f"{card['label']}：{statuses.get(card['state'], '未完成')}" for card in cards)
    parts = [review.text] if review.text else []
    if summary:
        parts.append(summary + '。')
    if not review.verified:
        parts.append('答复说明暂未完成核对；已保存的操作结果以上方记录为准。' if cards else '答复暂未完成核对，请重试答复核对；业务操作结果会保留。')
    elif review.execution_claims and not cards:
        parts.append('本次没有保存新的业务操作结果，未执行创建、修改、提交或删除。')
    elif not parts:
        parts.append('暂时缺少足够依据回答，请补充具体事项。')
    return '\n\n'.join(parts)
