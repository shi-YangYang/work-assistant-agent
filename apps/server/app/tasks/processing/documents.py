import asyncio
import hashlib
from dataclasses import dataclass
from app.integrations.parsing.formats import OFFICE_TARGETS
from app.integrations.parsing.office_conversion import office_version, parse_office
from app.core.errors import problem
from app.db.base import now
from app.integrations.parsing.document_parser import PARSER_VERSION
from app.integrations.parsing.process import parse_process
from app.modules.attachments.documents import attachment_dto
from app.modules.attachments.models import Attachment, DocumentChunk
from app.security.ownership import owned
from pathlib import Path
from sqlalchemy import delete
from weakref import WeakKeyDictionary


_parse_limits = WeakKeyDictionary()


@dataclass
class SharedParse:
    task: asyncio.Task
    users: int = 0


async def shared_parse(cache, key, operation, *, reuse_failure=False):
    entry = cache.get(key)
    created = entry is None or entry.task.cancelled()
    if created:
        entry = cache[key] = SharedParse(asyncio.create_task(operation()))
    entry.users += 1
    try:
        result = await asyncio.shield(entry.task)
        if not reuse_failure and not created and result['status'] not in ('ready', 'partial', 'empty'):
            return await operation()
        return result
    finally:
        entry.users -= 1
        if not entry.users and not entry.task.done():
            entry.task.cancel()
            await asyncio.gather(entry.task, return_exceptions=True)


async def prepare_document(context, identifier, *, parse_cache=None):
    from app.tasks.lease import lease
    def mark(event, **fields):
        if context.timing is not None:
            context.timing.mark(event, call=identifier, **fields)
    async def initialize(version=None):
        async with context.sessions.begin() as db:
            job, actor = await lease(db, context)
            item = await owned(db, Attachment, identifier, actor, lock=True)
            if item.kind != 'document' or (job.kind == 'message' and item.message_id != job.target_id) or (job.kind == 'document' and item.id != job.target_id):
                problem(404, '文档来源不可用')
            suffix = Path(item.name).suffix.lower()
            converting = suffix in OFFICE_TARGETS
            if converting and version is None:
                return None, suffix
            version = version if converting else PARSER_VERSION
            if item.extraction_status in ('ready', 'partial') and item.parser_version == version:
                mark('document.cache_hit', kind=suffix)
                return {'cached': attachment_dto(item)}, suffix
            item.extraction_revision += 1
            revision, checksum = item.extraction_revision, item.sha256
            item.extraction_status, item.parser_version, item.extraction_info = 'processing', version, {'stage': 'queued'} if converting else {}
            from app.modules.attachments.duplicates import content_key
            cache_key = (*content_key(item), version)
            from app.tasks.feedback.feedback_state import update_feedback
            update_feedback(job, 'parsing', '')
            job.phase, job.updated_at = 'document', now()
            return {'actor': actor, 'converting': converting, 'revision': revision, 'checksum': checksum, 'cache_key': cache_key}, suffix
    state, suffix = await initialize()
    if state is None:
        # A missing/cold executable probe must not hold a DB transaction/lock.
        version = await office_version()
        state, suffix = await initialize(version)
    if 'cached' in state:
        return state['cached']
    actor, converting, revision, checksum, cache_key = (state[key] for key in ('actor', 'converting', 'revision', 'checksum', 'cache_key'))
    mark('document.prepare', kind=suffix)
    path = context.settings.media_dir / identifier
    try:
        def digest_file():
            with path.open('rb') as source:
                return hashlib.file_digest(source, 'sha256').hexdigest()
        actual = await asyncio.to_thread(digest_file)
        if actual != checksum:
            raise ValueError('原文件校验失败，请重新上传')
        limit = _parse_limits.setdefault(asyncio.get_running_loop(), asyncio.Semaphore(2))
        async def stage(value):
            mark("document." + value, kind=suffix)
            async with context.sessions.begin() as db:
                await lease(db, context)
                current = await owned(db, Attachment, identifier, actor, lock=True)
                if current.extraction_revision == revision and current.extraction_status == 'processing':
                    current.extraction_info = {'stage': value}
        async def parse():
            if converting:
                return await parse_office(path, suffix, on_stage=stage)
            async with limit:
                return await parse_process(path, suffix)
        result = await parse() if parse_cache is None else await shared_parse(parse_cache, cache_key, parse, reuse_failure=converting)
    except asyncio.CancelledError:
        # An orderly worker shutdown/time budget must not leave a permanent
        # processing card. Hard crashes are recovered by the job lease instead.
        async with context.sessions.begin() as db:
            from app.tasks.context import LostLease
            from fastapi import HTTPException
            try:
                await lease(db, context)
                item = await owned(db, Attachment, identifier, actor, lock=True)
                if item.extraction_revision == revision:
                    item.extraction_status = 'failed'
                    item.extraction_info = {'error': '解析已中断，可重新解析'}
            except (LostLease, HTTPException):
                pass
        raise
    except (OSError, ValueError):
        result = {'status': 'failed', 'chunks': [], 'info': {'error': '原文件不可用或校验失败，请重新上传'}}
    async with context.sessions.begin() as db:
        await lease(db, context)
        item = await owned(db, Attachment, identifier, actor, lock=True)
        if item.extraction_revision != revision or item.sha256 != checksum:
            from app.tasks.context import InputChanged
            raise InputChanged(document=True)
        await db.execute(delete(DocumentChunk).where(DocumentChunk.attachment_id == item.id))
        for ordinal, chunk in enumerate(result['chunks']):
            db.add(DocumentChunk(company_id=item.company_id, owner_id=item.owner_id, attachment_id=item.id, revision=revision, ordinal=ordinal, location=chunk['location'], text=chunk['text']))
        item.extraction_status, item.extraction_info = result['status'], result['info']
        mark('document.prepared', kind=suffix, state=result['status'])
        return attachment_dto(item)
