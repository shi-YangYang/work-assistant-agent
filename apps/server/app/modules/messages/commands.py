from app.core.personas import DEFAULT_PERSONA
from app.core.attachment_limits import MAX_AUDIO_ATTACHMENTS, MAX_IMAGE_BYTES, MAX_FILE_BYTES
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
from app.tasks.conversation_activity import require_idle
from sqlalchemy import select


async def submit_message(db, actor, body, idempotency_key):
    payload = body.model_dump()
    if body.deliverableReference is None:
        payload.pop('deliverableReference')
    if body.personaId is None:
        # Do not add a default to historical, already-persisted request digests.
        payload.pop('personaId')
    if body.voiceCommandAttachmentId is None:
        payload.pop('voiceCommandAttachmentId')
    if body.voiceCommandAttachmentIds is None:
        payload.pop('voiceCommandAttachmentIds')
    if not body.newConversation:
        # Keep retries of older clients compatible with their stored digest.
        payload.pop('newConversation')
    prior, digest = await idem_begin(db, actor, 'message', idempotency_key, payload)
    if prior:
        await active_message(db, prior['messageId'], actor)
        return prior
    if body.newConversation:
        conversation = Conversation(company_id=actor.company_id, owner_id=actor.id, persona_id=body.personaId or DEFAULT_PERSONA)
        db.add(conversation)
        await db.flush()
    else:
        conversation = await owned(db, Conversation, body.conversationId, actor, lock=True) if body.conversationId else await default_conversation(db, actor, body.personaId)
    await require_idle(db, actor, conversation.id)
    if body.deliverableReference:
        from app.modules.deliverables.queries import check_reference
        await check_reference(db, actor, body.deliverableReference.model_dump(), conversation.id)
    attached = [await owned(db, Attachment, aid, actor, lock=True) for aid in body.attachmentIds]
    if any(a.message_id for a in attached):
        problem(422, '附件已用于其他消息，请重新上传')
    if any(a.size > (MAX_IMAGE_BYTES if a.kind == 'image' else MAX_FILE_BYTES) for a in attached):
        problem(422, '每张图片不能超过 30 MiB，其他单个文件不能超过 20 MiB')
    if sum(a.kind == 'audio' for a in attached) > MAX_AUDIO_ATTACHMENTS:
        problem(422, '每次最多 3 段语音，每段最长 3 分钟')
    voice_ids = body.voiceCommandAttachmentIds or ([body.voiceCommandAttachmentId] if body.voiceCommandAttachmentId else [])
    if any(not any(a.id == aid and a.kind == 'audio' for a in attached) for aid in voice_ids):
        problem(422, '语音指令必须使用本次发送的语音附件')
    if body.replyTo:
        reply = await active_message(db, body.replyTo, actor)
        await business_require(db, actor, reply.access)
        if reply.conversation_id != conversation.id:
            problem(422, '回复必须属于当前会话')
    item = Message(company_id=actor.company_id, owner_id=actor.id, conversation_id=conversation.id, persona_id=body.personaId or conversation.persona_id, text=body.text, reply_to=body.replyTo, deliverable_reference=body.deliverableReference.model_dump() if body.deliverableReference else {})
    db.add(item)
    await db.flush()
    from app.modules.conversations.task_state import begin_input
    await begin_input(db, actor, item)
    conversation.updated_at = now()
    if conversation.title == '新会话':
        conversation.title = body.text[:40] or ('文件上报' if attached[0].kind == 'document' else '图片上报' if attached[0].kind == 'image' else '语音上报')
        conversation.revision += 1
    for a in attached:
        a.message_id = item.id
        if a.kind == 'document':
            a.extraction_status = 'pending'
    job = Job(company_id=actor.company_id, owner_id=actor.id, kind='message', target_id=item.id, access=business_scope(actor), result={'attachmentOrder': body.attachmentIds, 'audioSources': [{'id': a.id, 'name': a.name} for a in attached if a.kind == 'audio'], **({'voiceCommandAttachmentId': body.voiceCommandAttachmentId} if body.voiceCommandAttachmentId else {}), **({'voiceCommandAttachmentIds': voice_ids} if body.voiceCommandAttachmentIds is not None else {})})
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
    from app.modules.messages.audio import transcript_groups
    job = await db.scalar(select(Job).where(Job.target_id == item.id, Job.kind == 'message'))
    try:
        transcript_groups(body.text, job.result if job else {})
    except ValueError as error:
        problem(422, str(error))
    item.transcript_history = [*item.transcript_history, {'revision': item.transcript_revision, 'text': item.transcript, 'at': now().isoformat()}]
    item.transcript, item.transcript_revision = body.text, item.transcript_revision + 1
    from app.modules.conversations.task_state import invalidate_sources
    await invalidate_sources(db, {item.id})
    from app.modules.conversations.context_invalidation import invalidate
    await invalidate(db, conversation_id=item.conversation_id, owner_id=item.owner_id)
    return await message_dto(db, item, actor)
