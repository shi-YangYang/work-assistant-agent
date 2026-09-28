"""Carry authorized conversational instructions across a report job boundary."""
from app.agent.conversation_context import conversation_references, message_reference, request_text
from app.core.digests import digest
from app.modules.messages.service import active_message
from app.security.access import require
from app.tasks.models import Job
from sqlalchemy import select


def reference_text(reference):
    return {key: reference.get(key, '') for key in ('userText', 'materialTranscript', 'assistantReference')}


async def capture_brief(db, actor, message, job):
    previous = await conversation_references(db, actor, job, message)
    references = []
    for ref in previous:
        if ref['id'] == 'context-summary':
            from app.modules.conversations.models import ConversationContext
            store = await db.get(ConversationContext, message.conversation_id)
            references.append({'id': 'context-summary', 'reference': ref, 'sources': store.payload.get('summarySources', {}),
                               'summaryAccess': store.payload.get('summaryAccess', {}), 'summaryDependencies': store.payload.get('summaryDependencies', {}),
                               'invalidationVersion': store.invalidation_version})
            continue
        original = await message_reference(db, actor, await active_message(db, ref['id'], actor))
        references.append({'id': ref['id'], 'input': digest(reference_text(ref)),
                           'fullInput': digest(reference_text(original)),
                           'lengths': {key: len(value) for key, value in reference_text(ref).items()},
                           'explicitReplyTarget': ref['explicitReplyTarget']})
    return {'messageId': message.id, 'input': digest(request_text(message, job)),
            'references': references,
            'materials': list(job.result.get('documentReads', {}).values()),
            'transcriptRevision': message.transcript_revision}


async def load_brief(db, actor, job):
    source = job.result.get('instructionSource')
    if not source:
        return []
    message = await active_message(db, source['messageId'], actor)
    await require(db, actor, message.access)
    message_job = await db.scalar(select(Job).where(Job.kind == 'message', Job.target_id == message.id, Job.owner_id == actor.id))
    if digest(request_text(message, message_job)) != source['input']:
        raise ValueError('报告写作要求已变化，请使用最新要求重新生成')
    references = []
    for item in source['references']:
        if item['id'] == 'context-summary':
            from app.modules.conversations.models import ConversationContext
            from app.modules.conversations.context_store import manifest, AccessCheck, summary_dependencies_valid
            store = await db.get(ConversationContext, message.conversation_id)
            if not store or store.invalidation_version != item['invalidationVersion']:
                raise ValueError('报告写作上下文已变化，请重新生成')
            if not await summary_dependencies_valid(db, actor, item):
                raise ValueError('报告引用的来源已变化或无权查看，请重新生成')
            stamps = await manifest(db, actor, message.conversation_id)
            check = AccessCheck(db, actor)
            for identifier, expected in item['sources'].items():
                stamp = stamps.get(identifier)
                if not stamp or stamp['deleted'] or stamp['source'] != expected['source'] or not await check.valid(stamp['access']):
                    raise ValueError('报告写作上下文已变化，请重新生成')
            references.append(item['reference'])
            continue
        previous = await active_message(db, item['id'], actor)
        if previous.conversation_id != message.conversation_id:
            raise ValueError('报告写作上下文已变化，请重新生成')
        await require(db, actor, previous.access)
        ref = await message_reference(db, actor, previous)
        # Match the same bounded projection captured for this report, while
        # hashing the full reference separately to detect edits to its tail.
        if item.get('fullInput') and digest(reference_text(ref)) != item['fullInput']:
            raise ValueError('报告引用的写作要求已变化，请使用最新要求重新生成')
        lengths = item.get('lengths', {'userText': 3000, 'materialTranscript': 2000, 'assistantReference': 5000})
        text = {key: ref.get(key, '')[:length] for key, length in lengths.items()}
        if digest(text) != item['input']:
            raise ValueError('报告引用的写作要求已变化，请使用最新要求重新生成')
        references.append({**ref, **text, 'explicitReplyTarget': item['explicitReplyTarget']})
    return references


async def load_materials(db, actor, job):
    """Resolve read source references, never promote them to confirmed facts."""
    from app.modules.attachments.documents import agent_attachment
    from app.modules.attachments.models import DocumentChunk
    source = job.result.get('instructionSource') or {}
    if not source:
        return []
    message = await active_message(db, source['messageId'], actor)
    await require(db, actor, message.access)
    message_job = await db.scalar(select(Job).where(Job.kind == 'message', Job.target_id == message.id, Job.owner_id == actor.id))
    if not message_job:
        raise ValueError('报告的原始请求已不可用，请重新生成')
    result = []
    for identifier, revision, ordinal in source.get('materials', []):
        document = await agent_attachment(db, identifier, actor, message_job)
        parent = await active_message(db, document.message_id, actor)
        await require(db, actor, parent.access)
        chunk = await db.scalar(select(DocumentChunk).where(DocumentChunk.attachment_id == identifier, DocumentChunk.revision == revision, DocumentChunk.ordinal == ordinal))
        if document.extraction_revision != revision or chunk is None:
            raise ValueError('报告引用的附件已变化，请使用最新材料重新生成')
        result.append({'name': document.name, 'location': chunk.location, 'text': chunk.text})
    from app.modules.messages.audio import transcript_groups
    _, material_transcript = transcript_groups(message.transcript, message_job.result)
    if material_transcript:
        if message.transcript_revision != source.get('transcriptRevision', message.transcript_revision):
            raise ValueError('报告引用的语音已更正，请使用最新材料重新生成')
        result.append({'name': '当前上传语音的转写', 'text': material_transcript})
    return result
