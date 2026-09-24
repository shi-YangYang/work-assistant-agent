from app.core.errors import problem
from app.modules.conversations.models import Conversation
from app.modules.messages.models import Message
from app.modules.messages.serializers import message_dto
from app.security.ownership import owned
from sqlalchemy import select


async def list_messages(db, actor, owner_id, cursor, limit, conversation_id=None):
    query = select(Message).where(Message.company_id == actor.company_id, Message.owner_id == owner_id, Message.deleted.is_(False), ~Message.conversation_id.in_(select(Conversation.id).where(Conversation.deleted.is_(True))))
    if conversation_id:
        query = query.where(Message.conversation_id == conversation_id)
    if cursor:
        anchor = await owned(db, Message, cursor, actor, read=True)
        if anchor.owner_id != owner_id or (conversation_id and anchor.conversation_id != conversation_id):
            problem(404, '分页位置不属于当前会话')
        query = query.where((Message.created_at < anchor.created_at) | ((Message.created_at == anchor.created_at) & (Message.id < anchor.id)))
    rows = list((await db.scalars(query.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit + 1))).all())
    return {'items': [await message_dto(db, m, actor) for m in rows[:limit]], 'nextCursor': rows[limit - 1].id if len(rows) > limit else None}
