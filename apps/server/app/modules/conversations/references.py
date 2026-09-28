"""Authoritative message and receipt projection used by conversation consumers."""
from app.modules.messages.audio import transcript_groups
from app.tasks.models import Job
from sqlalchemy import select


from app.modules.messages.input_text import request_text


async def message_reference(db, actor, message, *, job=None, job_loaded=False):
    from app.modules.operations.receipts import message_actions
    if not job_loaded:
        job = await db.scalar(select(Job).where(Job.kind == 'message', Job.target_id == message.id, Job.owner_id == actor.id))
    cards = await message_actions(db, actor, message)
    stored = job.result if job else {}
    # Only keep independently checked non-execution prose beside receipts.
    # Legacy replies may claim obsolete pending/success states, so omit those.
    reply = stored.get('conversationReply', '') if cards else message.reply
    return {
        'id': message.id, 'userText': request_text(message, job),
        'materialTranscript': transcript_groups(message.transcript, stored)[1],
        'assistantReference': reply,
        'currentActions': [{key: card[key] for key in ('id', 'action', 'state', 'objectId', 'objectRevision') if key in card} for card in cards],
    }

