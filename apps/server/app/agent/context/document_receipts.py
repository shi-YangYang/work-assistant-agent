"""Register source text receipts for both preloaded and tool-read documents."""
import json
from app.modules.attachments.models import Attachment


async def document_tool_result(db, context, item, result, job):
    from sqlalchemy import select
    from app.modules.attachments.duplicates import content_key
    from app.modules.attachments.documents import document_chunk_location, table_structure_reference
    equivalents = context.document_equivalents.get(item.id, {})
    others = []
    if equivalents and equivalents.get(item.id) == item.extraction_revision and item.message_id == job.target_id:
        candidates = (await db.scalars(select(Attachment).where(
            Attachment.id.in_(equivalents), Attachment.id != item.id,
            Attachment.company_id == item.company_id, Attachment.owner_id == item.owner_id,
            Attachment.message_id == job.target_id, Attachment.deleted.is_(False),
        ))).all()
        others = [other for other in candidates if content_key(other) == content_key(item)
                  and other.extraction_revision == equivalents[other.id]
                  and other.parser_version == item.parser_version
                  and other.extraction_status in ('ready', 'partial', 'empty')]
    aliases = dict(job.result.get('documentReadAliases', {}))
    rows = [*result['items'], *result.get('contextItems', [])]
    for row in rows:
        row['location'] = document_chunk_location(row['location'])
        token = f"{item.id}:{item.extraction_revision}:{row['ordinal']}"
        context.document_reads[token] = (item.id, item.extraction_revision, row['ordinal'])
        aliases.pop(token, None)
        row['citation'] = '[[file:' + token + ']]'
        for other in others:
            other_token = f"{other.id}:{other.extraction_revision}:{row['ordinal']}"
            if other_token not in context.document_reads:
                context.document_reads[other_token] = (other.id, other.extraction_revision, row['ordinal'])
                aliases[other_token] = item.id
    if others:
        result['sameContentAttachments'] = [{'id': other.id, 'name': other.name} for other in others]
        result['reuseScope'] = 'returned_chunks_only'
    if rows:
        result['positionBasis'] = {'source': 'location', 'cursor': 'ordinal_zero_based_fragment'}
    info = item.extraction_info or {}
    returned = {row['ordinal'] for row in rows}
    total = info.get('chunks', 0)
    cumulative = {entry[2] for entry in context.document_reads.values()
                  if entry[0] == item.id and entry[1] == item.extraction_revision}
    delivered = {entry[2] for entry in job.result.get('documentTextProvided', {}).values()
                 if entry[0] == item.id and entry[1] == item.extraction_revision}
    limits = []
    if len(cumulative) < total:
        limits.append('unreturned_text')
    if not info.get('sourceComplete'):
        limits.append('unextracted_source')
    if info.get('convertedFormat'):
        limits.append('conversion_fidelity_unverified')
    elif info.get('hasVisuals'):
        limits.append('visuals_not_read')
    result['readScope'] = {
        'returnedChunks': len(returned), 'extractedChunks': total,
        'allExtractedTextReturned': bool(total) and len(returned) == total,
        'returnedChunksThisTask': len(cumulative),
        'unreturnedExtractedChunksThisTask': max(0, total - len(cumulative)),
        'providedChunksBeforeThisCall': len(delivered),
        'textBasis': 'converted_text' if info.get('convertedFormat') else 'extracted_text',
        'pageImagesIncluded': False,
        'limitationsCodes': limits,
    }
    if structure := table_structure_reference(info):
        result['tableStructure'] = structure
    job.result = {**job.result, 'documentReads': context.document_reads, 'documentReadAliases': aliases}
    return json.dumps(result, ensure_ascii=False)
