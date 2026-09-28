from fastapi import HTTPException
from app.modules.interactions.queries import validate


async def interaction_dto(db, actor, row):
    base = {'id': row.id, 'messageId': row.message_id, 'conversationId': row.conversation_id, 'taskId': row.task_id, 'revision': row.revision, 'state': row.state, 'createdAt': row.created_at.isoformat(), 'questions': [], 'answers': [], 'continuation': row.continuation or None}
    try:
        await validate(db, actor, row, current=row.state == 'waiting')
    except HTTPException:
        return {**base, 'state': 'expired', 'continuation': None}
    # Trusted object IDs are internal; labels and option IDs suffice to answer.
    return {**base, 'questions': [{**question, 'options': [{k: v for k, v in option.items() if k in ('id', 'label', 'description')} for option in question['options']]} for question in row.questions], 'answers': row.answers}


async def message_interactions(db, actor, message):
    if actor.id != message.owner_id:
        return []
    from sqlalchemy import select
    from app.modules.interactions.models import AssistantInteraction
    rows = (await db.scalars(select(AssistantInteraction).where(AssistantInteraction.message_id == message.id, AssistantInteraction.owner_id == actor.id, AssistantInteraction.company_id == actor.company_id).order_by(AssistantInteraction.created_at))).all()
    return [await interaction_dto(db, actor, row) for row in rows]
