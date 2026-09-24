from app.modules.conversations.models import Conversation
from app.modules.messages.models import Message
from app.security.ownership import owned
from sqlalchemy import select


async def deleted_sources(db, ids):
    available = set((await db.scalars(select(Message.id).where(Message.id.in_(ids), Message.deleted.is_(False)))).all())
    return [identifier for identifier in ids if identifier not in available]


async def active_message(db, identifier, actor):
    message = await owned(db, Message, identifier, actor)
    if message.conversation_id:
        await owned(db, Conversation, message.conversation_id, actor)
    return message
