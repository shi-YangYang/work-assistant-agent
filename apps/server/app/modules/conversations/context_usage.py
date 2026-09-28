from app.modules.conversations.models import Conversation
from app.modules.messages.models import Message
from app.security.access import valid
from app.security.ownership import owned
from app.tasks.context_feedback import usage_dto
from app.tasks.models import Job
from sqlalchemy import select


async def latest_usage(db, actor, identifier):
    await owned(db, Conversation, identifier, actor)
    query = select(Job, Message.access).join(Message, Message.id == Job.target_id).where(
        Job.kind == 'message', Job.company_id == actor.company_id, Job.owner_id == actor.id,
        Message.conversation_id == identifier, Message.deleted.is_(False),
        Job.result.has_key('contextUsage')).order_by(Job.updated_at.desc(), Job.id.desc())
    for job, access in (await db.execute(query.limit(20))).all():
        if await valid(db, actor, job.access) and await valid(db, actor, access):
            return {'contextUsage': usage_dto(job)}
    return {'contextUsage': None}
