"""Authorized, bounded continuation with atomic append in the same generation."""
import asyncio
from pathlib import Path
from sqlalchemy import select
from app.modules.attachments.models import Attachment, DocumentChunk
from app.modules.attachments.documents import agent_attachment
from app.modules.attachments.document_assets import file_lock, generation, prepared_source
from app.integrations.parsing.process import parse_process
from app.tasks.lease import lease
from app.tasks.context import InputChanged


def merge_intervals(intervals):
    result = []
    for start, end in sorted(intervals):
        if result and start <= result[-1][1]:
            result[-1][1] = max(end, result[-1][1])
        else:
            result.append([start, end])
    return result


async def ensure_range(context, identifier, start=0):
    start = max(0, min(int(start), 10_000_000))
    async with context.sessions() as db:
        job, actor = await lease(db, context)
        item = await agent_attachment(db, identifier, actor, job)
        revision, checksum = item.extraction_revision, item.sha256
        initial = item.extraction_info or {}
        folder = generation(context.settings, item)
    from app.integrations.parsing.document_parser import PARSER_VERSION
    from app.integrations.parsing.formats import OFFICE_TARGETS
    from app.integrations.parsing.office_conversion import office_version
    expected = await office_version() if Path(item.name).suffix.lower() in OFFICE_TARGETS else PARSER_VERSION
    if item.extraction_status == 'failed' and item.parser_version == expected:
        # Reading a known failure must not silently repeat an expensive parse.
        # Explicit retries and a changed parser version can prepare it again.
        return {'error': initial.get('error') or '文件读取失败，请重新解析'}
    legacy = initial.get('schema') != 1 or item.parser_version != expected
    if not legacy:
        ranges = initial.get('extractedRanges', [initial.get('extractedRange', [0, 0])])
        if any(lo <= start < hi for lo, hi in ranges) or initial.get('sourceEnd') is not None and start >= initial['sourceEnd']:
            return initial
    if legacy:
        # A parser strategy upgrade starts a distinct generation; continuation
        # itself never changes a generation or repurposes old citation ordinals.
        from app.tasks.processing.documents import prepare_document
        refreshed = await prepare_document(context, identifier, allow_source=True)
        if refreshed['extraction'].get('schema') != 1 or refreshed['extraction'].get('parserVersion') != expected:
            return {'error': refreshed['extraction'].get('rangeError') or refreshed['extraction'].get('error', '文件读取失败')}
        return await ensure_range(context, identifier, start)
    async with file_lock(folder / 'text.lock'):
        async with context.sessions() as db:
            job, actor = await lease(db, context)
            item = await agent_attachment(db, identifier, actor, job)
            if item.extraction_revision != revision or item.sha256 != checksum:
                raise InputChanged(document=True)
            initial = item.extraction_info or {}
            ranges = initial.get('extractedRanges', [initial.get('extractedRange', [0, 0])])
            if any(lo <= start < hi for lo, hi in ranges) or initial.get('sourceEnd') is not None and start >= initial['sourceEnd']:
                return initial
        source, suffix = await prepared_source(context, item)
        from app.tasks.processing.documents import _parse_limits
        limit = _parse_limits.setdefault(asyncio.get_running_loop(), asyncio.Semaphore(2))
        async with limit:
            result = await parse_process(source, suffix, start=start)
        async with context.sessions.begin() as db:
            job, actor = await lease(db, context)
            item = await agent_attachment(db, identifier, actor, job)
            item = await db.scalar(select(Attachment).where(Attachment.id == item.id).with_for_update())
            if item.extraction_revision != revision or item.sha256 != checksum:
                raise InputChanged(document=True)
            if result['status'] == 'failed':
                # Failed continuation leaves committed earlier chunks usable.
                item.extraction_info = {**item.extraction_info, 'rangeError': result['info'].get('error', '部分内容无法读取')}
                return item.extraction_info
            existing = set((await db.scalars(select(DocumentChunk.ordinal).where(DocumentChunk.attachment_id == identifier, DocumentChunk.revision == revision,
                DocumentChunk.ordinal.in_([c['ordinal'] for c in result['chunks']])))).all()) if result['chunks'] else set()
            for chunk in result['chunks']:
                if chunk['ordinal'] not in existing:
                    db.add(DocumentChunk(company_id=item.company_id, owner_id=item.owner_id, attachment_id=identifier, revision=revision,
                                         ordinal=chunk['ordinal'], location=chunk['location'], text=chunk['text']))
            info = result['info']
            old = item.extraction_info or {}
            intervals = merge_intervals([*old.get('extractedRanges', [old.get('extractedRange', [0, 0])]), info['extractedRange']])
            source_end = info.get('sourceEnd', info['extractedRange'][1]) if info['sourceComplete'] else old.get('sourceEnd')
            complete = source_end is not None and intervals and intervals[0][0] == 0 and intervals[0][1] >= source_end
            warnings = list(dict.fromkeys(w for w in [*old.get('warnings', []), *info.get('warnings', [])] if w != '部分内容尚未读取，可继续读取后续范围'))
            if not complete:
                warnings.append('部分内容尚未读取，可继续读取后续范围')
            item.extraction_info = {**old, **info, 'characters': old.get('characters', 0) + sum(len(c['text']) for c in result['chunks'] if c['ordinal'] not in existing),
                'chunks': old.get('chunks', 0) + len(result['chunks']) - len(existing), 'extractedRanges': intervals, 'sourceEnd': source_end,
                'sourceComplete': complete, 'nextExtractCursor': None if complete else intervals[0][1] if intervals and intervals[0][0] == 0 else 0, 'warnings': warnings}
            item.extraction_info.pop('rangeError', None)
            item.extraction_status = 'partial' if warnings else 'ready'
            return item.extraction_info
