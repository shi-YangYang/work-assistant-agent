from app.modules.conversations.models import Conversation
from app.modules.messages.models import Message
from app.modules.conversations.serializers import conversation_dto
from app.security.ownership import owned
from sqlalchemy import func, or_, select


async def conversations_query(q, cursor, actor, db, *, order='updated'):
    query = select(Conversation).where(Conversation.owner_id == actor.id, Conversation.company_id == actor.company_id, Conversation.deleted.is_(False))
    if q.strip():
        query = query.where(Conversation.title.icontains(q.strip(), autoescape=True))
    if order == 'last_message':
        last_message = select(func.max(Message.created_at)).where(
            Message.conversation_id == Conversation.id, Message.owner_id == actor.id,
            Message.company_id == actor.company_id, Message.deleted.is_(False)
        ).correlate(Conversation).scalar_subquery()
        if cursor:
            anchor = await owned(db, Conversation, cursor, actor)
            stamp = await db.scalar(select(last_message).select_from(Conversation).where(Conversation.id == anchor.id))
            if stamp is not None:
                query = query.where(or_(last_message < stamp, (last_message == stamp) & (Conversation.id < anchor.id), last_message.is_(None)))
            else:
                query = query.where(last_message.is_(None), (Conversation.updated_at < anchor.updated_at) | ((Conversation.updated_at == anchor.updated_at) & (Conversation.id < anchor.id)))
        ordering = (last_message.desc().nulls_last(),
                    # Updated time is only a tie-breaker for conversations with no messages.
                    func.coalesce(last_message, Conversation.updated_at).desc(), Conversation.id.desc())
    else:
        ordering = (Conversation.updated_at.desc(), Conversation.id.desc())
    if cursor and order != 'last_message':
        anchor = await owned(db, Conversation, cursor, actor)
        query = query.where((Conversation.updated_at < anchor.updated_at) | ((Conversation.updated_at == anchor.updated_at) & (Conversation.id < anchor.id)))
    rows = list((await db.scalars(query.order_by(*ordering).limit(51))).all())
    return {'items': [conversation_dto(row) for row in rows[:50]], 'nextCursor': rows[49].id if len(rows) > 50 else None}
