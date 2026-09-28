import asyncio
from datetime import timedelta
from app.db.base import now
from app.modules.attachments.models import Attachment
from app.modules.members.models import Member
from app.modules.messages.models import Message
from app.modules.messages.service import active_message
from app.modules.reports.models import Report
from app.security.access import require as business_require, scope as business_scope
from app.security.locks import company_lock as business_company_lock
from app.security.ownership import owned
from app.tasks.context import InputChanged, LostLease
from app.tasks.models import Job
from sqlalchemy import select


async def heartbeat(context):
    while True:
        await asyncio.sleep(15)
        async with context.sessions.begin() as db:
            job, _ = await lease(db, context)
            job.lease_until = now() + timedelta(seconds=90)


async def lease(db, context):
    await business_company_lock(db, context.company_id)
    actor = await db.scalar(select(Member).where(Member.id == context.owner_id).with_for_update())
    job = await db.scalar(select(Job).where(Job.id == context.job_id).with_for_update())
    if job is None or job.state != 'running' or job.fence != context.fence or job.lease_until < now() or not actor or not actor.active or actor.company_id != context.company_id:
        raise LostLease()
    if job.access and job.access.get('role') != actor.role:
        raise ValueError('账号权限已变化，请重新提问；旧处理已停止')
    await business_require(db, actor, job.access)
    if context.context_sources:
        from app.modules.conversations.models import ConversationContext
        source = await db.get(Message, job.target_id) if job.kind == 'message' else None
        epoch = await db.scalar(select(ConversationContext.invalidation_version).where(
            ConversationContext.conversation_id == source.conversation_id,
            ConversationContext.owner_id == actor.id, ConversationContext.company_id == actor.company_id)) if source and source.conversation_id else None
        if epoch is None or epoch != context.context_sources['invalidationVersion']:
            raise InputChanged()
    context.access = job.access or business_scope(actor)
    context.role = actor.role
    context.own_work_searched = job.result.get('ownWorkSearched', False)
    if job.kind == 'document':
        attachment = await owned(db, Attachment, job.target_id, actor)
        await active_message(db, attachment.message_id, actor)
    elif job.kind == 'message':
        await active_message(db, job.target_id, actor)
    else:
        await owned(db, Report, job.target_id, actor)
        if actor.role != 'employee':
            raise LostLease()
    if job.kind == 'message' and context.source_revision is not None:
        # Hold this lock through each write, so a transcript PATCH cannot commit
        # between validating its revision and saving a tool result or final reply.
        message = await owned(db, Message, job.target_id, actor, lock=True)
        from app.modules.conversations.task_state import assert_current
        await assert_current(db, actor, job, message)
        if message.transcript_revision != context.source_revision:
            raise InputChanged()
    for identifier, revision in context.document_versions.items():
        attachment = await owned(db, Attachment, identifier, actor)
        if attachment.extraction_revision != revision:
            raise InputChanged(document=True)
    for identifier, message_id in context.image_sources.items():
        attachment = await owned(db, Attachment, identifier, actor)
        parent = await active_message(db, message_id, actor)
        if attachment.message_id != parent.id or attachment.kind != 'image':
            raise ValueError('引用的图片已不可用，请重新发送')
        await business_require(db, actor, parent.access)
    return job, actor
