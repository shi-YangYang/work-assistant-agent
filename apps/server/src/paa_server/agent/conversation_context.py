import json
from paa_server.modules.messages.models import Message
from paa_server.modules.messages.service import active_message
from paa_server.security.access import merge_access as business_merge_access, scope as business_scope, valid as business_valid
from paa_server.tasks.models import Job
from sqlalchemy import select


def request_text(message, job):
    # The API records this explicit client choice only for an attached audio.
    # Uploaded audio remains reference material; transcript corrections keep the choice.
    voice = message.transcript if job and job.result.get('voiceCommandAttachmentId') else ''
    return '\n'.join(part for part in (message.text, voice) if part.strip())


async def message_reference(db, actor, message):
    from paa_server.modules.operations.receipts import message_actions
    job = await db.scalar(select(Job).where(Job.kind == 'message', Job.target_id == message.id, Job.owner_id == actor.id))
    cards = await message_actions(db, actor, message)
    stored = job.result if job else {}
    # Only keep independently checked non-execution prose beside receipts.
    # Legacy replies may claim obsolete pending/success states, so omit those.
    reply = stored.get('conversationReply', '') if cards else message.reply
    return {
        'id': message.id, 'userText': request_text(message, job),
        'materialTranscript': '' if stored.get('voiceCommandAttachmentId') else message.transcript,
        'assistantReference': reply,
        'currentActions': [{key: card[key] for key in ('id', 'action', 'state', 'objectId', 'objectRevision') if key in card} for card in cards],
    }


async def conversation_references(db, actor, job, current, budget=12000):
    rows = list((await db.scalars(select(Message).where(Message.owner_id == actor.id, Message.company_id == actor.company_id, Message.id != current.id, Message.deleted.is_(False), Message.conversation_id == current.conversation_id, Message.created_at <= current.created_at).order_by(Message.created_at.desc(), Message.id.desc()).limit(12))).all())
    if current.reply_to:
        parent = await active_message(db, current.reply_to, actor)
        if parent.conversation_id != current.conversation_id:
            raise ValueError('回复上下文不属于当前会话')
        rows = [parent, *(row for row in rows if row.id != parent.id)]
    selected = []
    for row in rows:
        if not await business_valid(db, actor, row.access):
            continue
        reference = await message_reference(db, actor, row)
        reference['userText'] = reference['userText'][:3000]
        reference['materialTranscript'] = reference['materialTranscript'][:2000]
        reference['assistantReference'] = reference['assistantReference'][:5000]
        reference['explicitReplyTarget'] = row.id == current.reply_to
        size = len(json.dumps(reference, ensure_ascii=False))
        if size > budget:
            continue
        budget -= size
        job.access = business_merge_access(job.access or business_scope(actor), row.access)
        selected.append((row.created_at, row.id, reference))
    return [reference for _, _, reference in sorted(selected)]
