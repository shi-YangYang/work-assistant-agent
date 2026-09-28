"""Persist interruption before cancelling the local execution and its IO."""
import asyncio
from app.core.errors import problem
from app.core.schemas import Input
from app.db.base import now
from app.modules.attachments.models import Attachment
from app.modules.messages.service import active_message
from app.modules.model_services.usage import interrupt_usage
from app.security.access import require as business_require
from app.security.locks import company_lock
from app.security.ownership import owned
from app.tasks.context import LostLease
from app.tasks.feedback_state import update_feedback
from app.tasks.lease import heartbeat
from app.tasks.models import Job
from app.tasks.node_state import cancel_unfinished
from pydantic import Field
from sqlalchemy import select

CANCEL_POLL_SECONDS = 2


class CancelJob(Input):
    expectedAttempt: int = Field(ge=0, strict=True)
    expectedFence: int = Field(ge=0, strict=True)


async def cancel_job(db, actor, identifier, body):
    await company_lock(db, actor.company_id)
    item = await owned(db, Job, identifier, actor, lock=True)
    if item.kind != 'message':
        problem(409, '仅工作助手消息任务可以中断')
    message = await active_message(db, item.target_id, actor)
    await business_require(db, actor, item.access)
    await business_require(db, actor, message.access)
    if item.access and item.access.get('role') != actor.role:
        problem(403, '账号权限已变化，请重新提问')
    if item.state not in ('queued', 'running'):
        return item
    if item.attempt != body.expectedAttempt or item.fence != body.expectedFence:
        problem(409, '任务执行版本已变化，请刷新后中断', 'job_version_changed')
    await interrupt_usage(db, item)
    item.state, item.phase, item.error = 'cancelled', 'cancelled', '已中断'
    item.fence, item.lease_until, item.updated_at = item.fence + 1, None, now()
    item.result = {key: value for key, value in item.result.items() if key not in ('pendingReply', 'replyReviewError')}
    cancel_unfinished(item)
    update_feedback(item, text='')
    if item.result.get('contextUsage'):
        item.result = {**item.result, 'contextUsage': {
            **item.result['contextUsage'], 'state': 'failed', 'fence': item.fence,
            'attempt': item.attempt, 'seq': item.feedback['seq'],
        }}
    documents = (await db.scalars(select(Attachment).where(
        Attachment.message_id == message.id, Attachment.owner_id == actor.id,
        Attachment.company_id == actor.company_id, Attachment.deleted.is_(False),
        Attachment.kind == 'document', Attachment.extraction_status.in_(('pending', 'processing')),
    ).with_for_update())).all()
    for document in documents:
        document.extraction_status = 'failed'
        document.extraction_info = {'error': '解析已中断，可重新解析'}
    return item


async def watch_cancellation(context):
    while True:
        # Select only the execution identity, without taking locks or loading
        # node outputs/context JSON while an external call is in flight.
        async with context.sessions() as db:
            row = (await db.execute(select(Job.state, Job.fence, Job.lease_until).where(
                Job.id == context.job_id, Job.owner_id == context.owner_id,
                Job.company_id == context.company_id,
            ))).one_or_none()
        if not row or row.state != 'running' or row.fence != context.fence or row.lease_until is None or row.lease_until < now():
            raise LostLease()
        await asyncio.sleep(CANCEL_POLL_SECONDS)


async def run_until_interrupted(context, operation):
    execution = asyncio.create_task(operation)
    observers = [asyncio.create_task(heartbeat(context)), asyncio.create_task(watch_cancellation(context))]
    tasks = [execution, *observers]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if execution in done:
            return await execution
        # Wait for HTTP streams, parser children and nested tools to release
        # resources before the worker slot can claim another job.
        execution.cancel()
        await asyncio.gather(execution, return_exceptions=True)
        for observer in observers:
            if observer in done:
                await observer
        raise LostLease()
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
