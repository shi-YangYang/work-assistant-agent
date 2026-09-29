"""Settle question state without depending on agent or task orchestration."""
from sqlalchemy import select
from app.db.base import now
from app.modules.interactions.models import AssistantInteraction
from app.modules.members.models import Member
from app.modules.messages.models import Message
from app.security.ownership import owned
from app.tasks.runtime.waiting import settle


async def expire(db, *, message_ids=(), conversation_id=None, owner_id=None):
    filters = [AssistantInteraction.state == 'waiting']
    if message_ids:
        filters.append(AssistantInteraction.message_id.in_(message_ids))
    elif conversation_id:
        filters.append(AssistantInteraction.conversation_id == conversation_id)
    elif owner_id:
        filters.append(AssistantInteraction.owner_id == owner_id)
    else:
        return
    for row in (await db.scalars(select(AssistantInteraction).where(*filters).with_for_update())).all():
        row.state, row.updated_at = 'expired', now()
        row.revision += 1
        actor = await db.get(Member, row.owner_id)
        if actor:
            await settle(db, actor, row.message_id)


async def settle_natural_reply(db, actor, job, interpretation):
    candidate = job.result.get('questionCandidate')
    if not candidate:
        return
    row = await db.get(AssistantInteraction, candidate)
    if not row or row.state != 'waiting':
        return
    message = await owned(db, Message, job.target_id, actor)
    if interpretation.get('relation') == 'continue':
        row.state, row.answers = 'answered', [{'questionId': question['id'], 'optionIds': [], 'text': message.text} for question in row.questions]
        row.continuation = {'messageId': message.id, 'jobId': job.id, 'conversationId': message.conversation_id}
    else:
        row.state = 'expired'
    row.revision += 1
    row.updated_at = now()
    await settle(db, actor, row.message_id)
