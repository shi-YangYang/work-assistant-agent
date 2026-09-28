from app.core.errors import problem
from app.modules.conversations.models import Conversation
from app.modules.deliverables.models import Deliverable, DeliverableRevision
from app.security.access import require
from app.security.ownership import owned
from sqlalchemy import select


async def get_deliverable(db, actor, identifier, revision=None, *, conversation_id=None, lock=False):
    item = await owned(db, Deliverable, identifier, actor, lock=lock)
    await owned(db, Conversation, item.conversation_id, actor)
    await require(db, actor, item.access)
    if conversation_id is not None and item.conversation_id != conversation_id:
        problem(404, '成果不属于当前会话')
    record = await db.scalar(select(DeliverableRevision).where(DeliverableRevision.deliverable_id == item.id, DeliverableRevision.revision == (revision or item.revision)))
    if not record:
        problem(404, '成果版本不存在')
    return item, record


async def check_reference(db, actor, reference, conversation_id):
    item, record = await get_deliverable(db, actor, reference['id'], reference['revision'], conversation_id=conversation_id)
    if set(reference.get('itemIds', [])) - {entry['id'] for entry in record.items}:
        problem(409, '所选条目不属于该成果版本，请重新选择')
    return item, record


async def conversation_deliverables(db, actor, conversation_id, offset=0):
    await owned(db, Conversation, conversation_id, actor)
    return list((await db.scalars(select(Deliverable).where(Deliverable.company_id == actor.company_id, Deliverable.owner_id == actor.id, Deliverable.conversation_id == conversation_id).order_by(Deliverable.updated_at.desc(), Deliverable.id).offset(offset).limit(21))).all())
