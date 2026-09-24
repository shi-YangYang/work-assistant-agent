from app.core.errors import problem
from app.db.base import now
from app.db.idempotency import idem_begin, idem_save
from app.modules.attachments.models import Attachment
from app.modules.conversations.models import Conversation
from app.modules.conversations.service import default_conversation
from app.modules.messages.models import Message
from app.modules.messages.serializers import message_dto
from app.modules.messages.service import active_message
from app.security.access import require as business_require, scope as business_scope
from app.security.ownership import owned
from app.tasks.models import Job
from sqlalchemy import select


async def submit_message(db, actor, body, idempotency_key):
    payload = body.model_dump()
    if body.voiceCommandAttachmentId is None:
        payload.pop('voiceCommandAttachmentId')
    if not body.newConversation:
        # Keep retries of older clients compatible with their stored digest.
        payload.pop('newConversation')
    prior, digest = await idem_begin(db, actor, 'message', idempotency_key, payload)
    if prior:
        await active_message(db, prior['messageId'], actor)
        return prior
    if body.newConversation:
        conversation = Conversation(company_id=actor.company_id, owner_id=actor.id)
        db.add(conversation)
        await db.flush()
    else:
        conversation = await owned(db, Conversation, body.conversationId, actor, lock=True) if body.conversationId else await default_conversation(db, actor)
    attached = [await owned(db, Attachment, aid, actor, lock=True) for aid in body.attachmentIds]
    if any(a.message_id for a in attached) or sum(a.size for a in attached) > 20 * 1024 * 1024 or sum(a.kind == 'audio' for a in attached) > 1:
        problem(422, '附件已使用或组合不受支持；附件合计最多 4 个、20 MiB，其中最多一段语音')
    if body.voiceCommandAttachmentId is not None and not any(a.id == body.voiceCommandAttachmentId and a.kind == 'audio' for a in attached):
        problem(422, '语音指令必须使用本次发送的语音附件')
    if body.replyTo:
        reply = await active_message(db, body.replyTo, actor)
        await business_require(db, actor, reply.access)
        if reply.conversation_id != conversation.id:
            problem(422, '回复必须属于当前会话')
    item = Message(company_id=actor.company_id, owner_id=actor.id, conversation_id=conversation.id, text=body.text, reply_to=body.replyTo)
    db.add(item)
    await db.flush()
    conversation.updated_at = now()
    if conversation.title == '新会话':
        conversation.title = body.text[:40] or ('文件上报' if attached[0].kind == 'document' else '图片上报' if attached[0].kind == 'image' else '语音上报')
        conversation.revision += 1
    for a in attached:
        a.message_id = item.id
        if a.kind == 'document':
            a.extraction_status = 'pending'
    job = Job(company_id=actor.company_id, owner_id=actor.id, kind='message', target_id=item.id, access=business_scope(actor), result={'attachmentOrder': body.attachmentIds, **({'voiceCommandAttachmentId': body.voiceCommandAttachmentId} if body.voiceCommandAttachmentId else {})})
    db.add(job)
    await db.flush()
    return idem_save(db, actor, 'message', idempotency_key, digest, {'messageId': item.id, 'jobId': job.id, 'conversationId': conversation.id})


async def correct_transcript(db, actor, identifier, body):
    item = await owned(db, Message, identifier, actor, lock=True)
    await active_message(db, identifier, actor)
    if not await db.scalar(select(Attachment.id).where(Attachment.message_id == item.id, Attachment.kind == 'audio')):
        problem(422, '仅语音消息可以修正转写')
    if item.transcript_revision != body.expectedRevision:
        problem(409, '转写已被更新，请读取最新内容')
    item.transcript_history = [*item.transcript_history, {'revision': item.transcript_revision, 'text': item.transcript, 'at': now().isoformat()}]
    item.transcript, item.transcript_revision = body.text, item.transcript_revision + 1
    return await message_dto(db, item, actor)
