"""Message admission and activity share the existing company/owner write lock."""
from app.core.errors import problem
from app.modules.conversations.models import Conversation
from app.modules.messages.models import Message
from app.modules.messages.service import active_message
from app.security.access import require as business_require, valid as business_valid
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


async def account_activity(db, actor):
    """Minimal current-owner snapshot; administrators do not get a team overview."""
    rows = (await db.execute(select(Job, Message).join(Message, Message.id == Job.target_id)
        .outerjoin(Conversation, Conversation.id == Message.conversation_id).where(
            Job.company_id == actor.company_id, Job.owner_id == actor.id,
            Job.kind == 'message', Job.state.in_(('queued', 'running')),
            Message.company_id == actor.company_id, Message.owner_id == actor.id,
            Message.deleted.is_(False),
            (Message.conversation_id.is_(None)) | (
                (Conversation.company_id == actor.company_id) &
                (Conversation.owner_id == actor.id) & Conversation.deleted.is_(False)),
        ).order_by(Job.created_at, Job.id))).all()
    jobs = []
    for job, message in rows:
        if job.access and job.access.get('role') != actor.role:
            continue
        if not await business_valid(db, actor, job.access) or not await business_valid(db, actor, message.access):
            continue
        jobs.append({'id': job.id, 'conversationId': message.conversation_id,
            'targetId': job.target_id, 'state': job.state,
            'stage': (job.feedback or {}).get('stage', 'queued'),
            'attempt': job.attempt, 'fence': job.fence,
            'seq': (job.feedback or {}).get('seq', 0), 'updatedAt': job.updated_at.isoformat()})
    return {'jobs': jobs}
