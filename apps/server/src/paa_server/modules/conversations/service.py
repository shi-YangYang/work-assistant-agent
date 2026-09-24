from paa_server.modules.conversations.models import Conversation
from paa_server.modules.members.models import Member
from sqlalchemy import select


async def default_conversation(db, actor):
    await db.scalar(select(Member).where(Member.id == actor.id).with_for_update())
    item = await db.scalar(select(Conversation).where(Conversation.owner_id == actor.id, Conversation.deleted.is_(False)).order_by(Conversation.created_at).limit(1))
    if item is None:
        item = Conversation(company_id=actor.company_id, owner_id=actor.id)
        db.add(item)
        await db.flush()
    return item
