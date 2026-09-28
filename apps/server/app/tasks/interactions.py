"""Durable continuation admission; no model or worker lease lives across a reply."""
from app.db.base import now
from app.modules.conversations.models import Conversation
from app.modules.messages.models import Message
from app.security.ownership import owned
from app.security.access import require, scope
from app.tasks.models import Job
from app.tasks.conversation_activity import require_idle
from sqlalchemy import select


async def continue_task(db, actor, source, text, *, reference, task_id):
    conversation = await owned(db, Conversation, source.conversation_id, actor, lock=True)
    await require(db, actor, source.access)
    await require_idle(db, actor, conversation.id)
    message = Message(company_id=actor.company_id, owner_id=actor.id, conversation_id=conversation.id, persona_id=conversation.persona_id, text=text, reply_to=source.id)
    db.add(message)
    await db.flush()
    from app.modules.conversations.task_state import begin_input
    await begin_input(db, actor, message)
    result = {'executionMode': conversation.execution_mode, 'modeRevision': conversation.mode_revision, 'continuation': {'sourceMessageId': source.id, 'taskId': task_id, **reference}}
    job = Job(company_id=actor.company_id, owner_id=actor.id, kind='message', target_id=message.id, access=scope(actor), result=result)
    db.add(job)
    conversation.updated_at = now()
    await db.flush()
    return {'messageId': message.id, 'jobId': job.id, 'conversationId': conversation.id}


async def continue_approval(db, actor, row):
    if row.continuation:
        return row.continuation
    from app.modules.operations.models import BusinessAction
    # One run continues all choices once the remaining cards are resolved.
    pending = await db.scalar(select(BusinessAction.id).where(BusinessAction.task_id == row.task_id, BusinessAction.company_id == actor.company_id, BusinessAction.owner_id == actor.id, BusinessAction.state == 'pending').limit(1))
    if pending or not row.task_id:
        return None
    source = await owned(db, Message, row.message_id, actor)
    from app.modules.conversations.models import ConversationTaskState
    state = await db.get(ConversationTaskState, row.conversation_id)
    if state and (state.payload.get('task', {}).get('id') != row.task_id or state.payload.get('task', {}).get('state') == 'cancelled'):
        return None
    from app.modules.operations.rules import LABELS
    text = ('已确认' if row.state in ('succeeded', 'running') else '已取消') + LABELS[row.action] + '。请继续原任务的其余事项，已完成的操作不要重复。'
    result = await continue_task(db, actor, source, text, reference={'actionId': row.id}, task_id=row.task_id)
    siblings = (await db.scalars(select(BusinessAction).where(
        BusinessAction.message_id == row.message_id, BusinessAction.task_id == row.task_id,
        BusinessAction.company_id == actor.company_id, BusinessAction.owner_id == actor.id,
        BusinessAction.state.in_(('succeeded', 'running', 'cancelled'))).with_for_update())).all()
    for sibling in siblings:
        if not sibling.continuation:
            sibling.continuation = result
    return result
