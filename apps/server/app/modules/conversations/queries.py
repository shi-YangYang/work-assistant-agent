from app.modules.conversations.models import Conversation
from app.modules.conversations.serializers import conversation_dto
from app.security.ownership import owned
from sqlalchemy import select


async def conversations_query(q, cursor, actor, db):
    query = select(Conversation).where(Conversation.owner_id == actor.id, Conversation.company_id == actor.company_id, Conversation.deleted.is_(False))
    if q.strip():
        query = query.where(Conversation.title.icontains(q.strip(), autoescape=True))
    if cursor:
        anchor = await owned(db, Conversation, cursor, actor)
        query = query.where((Conversation.updated_at < anchor.updated_at) | ((Conversation.updated_at == anchor.updated_at) & (Conversation.id < anchor.id)))
    rows = list((await db.scalars(query.order_by(Conversation.updated_at.desc(), Conversation.id.desc()).limit(51))).all())
    return {'items': [conversation_dto(row) for row in rows[:50]], 'nextCursor': rows[49].id if len(rows) > 50 else None}
