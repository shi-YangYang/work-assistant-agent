"""Invalidate rebuildable conversation projections without loading agent execution."""
from app.db.base import now
from app.modules.conversations.models import ConversationContext
from sqlalchemy import delete, select


async def invalidate(db, *, conversation_id=None, owner_id=None, company_id=None):
    query = select(ConversationContext)
    for field, value in (('conversation_id', conversation_id), ('owner_id', owner_id), ('company_id', company_id)):
        if value is not None:
            query = query.where(getattr(ConversationContext, field) == value)
    for store in (await db.scalars(query.with_for_update())).all():
        store.payload = {}
        store.invalidation_version += 1
        store.revision += 1
        store.updated_at = now()


async def remove(db, conversation_id):
    from app.modules.conversations.models import ConversationTaskState
    await db.execute(delete(ConversationTaskState).where(ConversationTaskState.conversation_id == conversation_id))
    await db.execute(delete(ConversationContext).where(ConversationContext.conversation_id == conversation_id))
