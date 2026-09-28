"""Private suggestion cards reused by a continuing task without duplicate drafts."""
from app.modules.messages.models import Message
from app.modules.work.models import ProgressDraft
from app.security.access import valid
from app.tasks.items import collect
from sqlalchemy import select


async def message_drafts(db, actor, message, job=None):
    if message.owner_id != actor.id or message.company_id != actor.company_id or not await valid(db, actor, message.access):
        return []
    references = {item['receiptId'] for item in collect(job) if item['action'] in ('propose_progress', 'propose_followup') and item.get('receiptId')} if job else set()
    rows = (await db.execute(select(ProgressDraft, Message).join(Message, Message.id == ProgressDraft.message_id).where(
        (ProgressDraft.message_id == message.id) | ProgressDraft.id.in_(references),
        ProgressDraft.company_id == actor.company_id, ProgressDraft.owner_id == actor.id,
        ProgressDraft.status != 'deleted', Message.company_id == actor.company_id, Message.owner_id == actor.id,
        Message.conversation_id == message.conversation_id, Message.deleted.is_(False)
    ).order_by(ProgressDraft.created_at))).all()
    return [draft for draft, source in rows if await valid(db, actor, draft.access) and await valid(db, actor, source.access)]
