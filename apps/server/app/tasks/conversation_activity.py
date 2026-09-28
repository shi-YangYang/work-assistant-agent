"""Message admission and activity share the existing company/owner write lock."""
from app.core.errors import problem
from app.modules.conversations.models import Conversation
from app.modules.messages.models import Message
from app.modules.messages.service import active_message
from app.security.access import require as business_require
from app.security.ownership import owned
from app.tasks.models import Job
from sqlalchemy import case, select


async def active_job(db, actor, conversation_id):
    return await db.scalar(select(Job).join(Message, Message.id == Job.target_id).where(
        Job.company_id == actor.company_id, Job.owner_id == actor.id,
        Job.kind == 'message', Job.state.in_(('queued', 'running')),
        Message.company_id == actor.company_id, Message.owner_id == actor.id,
        Message.conversation_id == conversation_id, Message.deleted.is_(False),
    ).order_by(case((Job.state == 'running', 0), else_=1), Job.created_at, Job.id).limit(1))


async def require_idle(db, actor, conversation_id):
    # Callers hold company -> owner before taking any conversation/job locks.
    # This also serializes admission for legacy messages without a conversation.
    if await active_job(db, actor, conversation_id):
        problem(409, '当前会话仍在处理中，请先中断或等待完成', 'conversation_busy')


async def current_job(db, actor, conversation_id):
    await owned(db, Conversation, conversation_id, actor)
    job = await active_job(db, actor, conversation_id)
    if job:
        await business_require(db, actor, job.access)
        message = await active_message(db, job.target_id, actor)
        await business_require(db, actor, message.access)
        if job.access and job.access.get('role') != actor.role:
            problem(403, '账号权限已变化，请重新提问', 'business_access_changed')
    return job
