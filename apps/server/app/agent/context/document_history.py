"""Carry forward already delivered source text, never historical model claims."""
import json
from collections import defaultdict

from fastapi import HTTPException
from langchain_core.messages import HumanMessage
from sqlalchemy import select

from app.agent.context.context_usage import estimate_request, input_budget
from app.agent.context.document_input import PRELOAD_CHARACTERS
from app.modules.attachments.documents import agent_attachment, document_chunk_location, document_reference
from app.modules.attachments.models import DocumentChunk
from app.security.access import merge_access, require, scope
from app.tasks.models import Job


async def previous_document_text(db, context, job, actor, references, content):
    previous = context.context_sources.get('previousMessageId')
    if not context.document_snapshot or not previous or previous not in {row['id'] for row in references}:
        return None
    origin = await db.scalar(select(Job).where(Job.kind == 'message', Job.target_id == previous,
                                              Job.owner_id == actor.id, Job.company_id == actor.company_id))
    if origin is None or not origin.result.get('documentTextProvided'):
        return None
    try:
        await require(db, actor, origin.access)
    except HTTPException:
        return None
    groups = defaultdict(set)
    for evidence in origin.result['documentTextProvided'].values():
        if (isinstance(evidence, (list, tuple)) and len(evidence) == 3
                and isinstance(evidence[0], str) and type(evidence[1]) is int and type(evidence[2]) is int
                and evidence[1] > 0 and evidence[2] >= 0 and evidence[0] not in context.current_document_ids):
            groups[(evidence[0], evidence[1])].add(evidence[2])
    limit = input_budget(context, 4000)
    used = estimate_request([{'role': 'user', 'content': content},
                             {'role': 'user', 'content': json.dumps(references, ensure_ascii=False)}])
    available = max(0, (limit if limit is not None else 64000) - used - 4096)
    remaining = min(PRELOAD_CHARACTERS, available // 2)
    text, reads = '', {}
    for (identifier, revision), ordinals in sorted(groups.items()):
        if not remaining or len(ordinals) > 2000:
            continue
        try:
            item = await agent_attachment(db, identifier, actor, job)
        except HTTPException:
            continue
        if item.extraction_revision != revision:
            continue
        chunks = list((await db.scalars(select(DocumentChunk).where(
            DocumentChunk.attachment_id == identifier, DocumentChunk.revision == revision,
            DocumentChunk.ordinal.in_(ordinals)).order_by(DocumentChunk.ordinal))).all())
        # Preserve each prior source as a whole observed set; never silently
        # drop its late qualification or fill gaps with unprovided fragments.
        size = sum(len(chunk.text) for chunk in chunks)
        if len(chunks) != len(ordinals) or size > remaining:
            continue
        info = item.extraction_info or {}
        extraction = document_reference(item)['extraction']
        receipt = {'attachment': {'id': identifier, 'name': item.name, 'revision': revision,
                                  'extraction': {key: extraction[key] for key in
                                      ('status', 'scope', 'sourceComplete', 'hasVisuals', 'originalFormat', 'convertedFormat',
                                       'visualDetectionBasis', 'conversionFidelityVerified', 'visualError', 'rangeError')
                                      if key in extraction}},
                   'sourceMessageId': item.message_id, 'sourceCreatedAt': item.created_at.isoformat(),
                   'evidenceType': 'stored_file_text',
                   'items': [{'ordinal': chunk.ordinal, 'location': document_chunk_location(chunk.location),
                              'text': chunk.text, 'citation': f'[[file:{identifier}:{revision}:{chunk.ordinal}]]'} for chunk in chunks],
                   'readScope': {'sourceComplete': bool(info.get('sourceComplete')),
                                 'allExtractedTextReturned': len(chunks) == info.get('chunks'),
                                 'pageImagesIncluded': False, 'warnings': info.get('warnings', []),
                                 'textBasis': 'converted_text' if info.get('convertedFormat') else 'extracted_text'}}
        addition = '\n已提供文档正文：' + json.dumps(receipt, ensure_ascii=False)
        if estimate_request([{'role': 'user', 'content': text + addition}]) > available:
            continue
        text += addition
        remaining -= size
        context.document_versions[identifier] = revision
        reads.update({f'{identifier}:{revision}:{chunk.ordinal}': (identifier, revision, chunk.ordinal) for chunk in chunks})
    if not reads:
        return None
    context.document_reads.update(reads)
    job.access = merge_access(job.access or scope(actor), origin.access)
    job.result = {**job.result, 'documentReads': {**job.result.get('documentReads', {}), **reads}}
    return HumanMessage(id=f'history-material:{previous}', content=[{'type': 'text', 'text': text}])
