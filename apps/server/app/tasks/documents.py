import asyncio
import hashlib
from app.core.errors import problem
from app.db.base import now
from app.integrations.parsing.document_parser import PARSER_VERSION
from app.integrations.parsing.process import parse_process
from app.modules.attachments.documents import attachment_dto
from app.modules.attachments.models import Attachment, DocumentChunk
from app.security.ownership import owned
from pathlib import Path
from sqlalchemy import delete


async def prepare_document(context, identifier):
    from app.tasks.lease import lease
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        item = await owned(db, Attachment, identifier, actor, lock=True)
        if item.kind != 'document' or (job.kind == 'message' and item.message_id != job.target_id) or (job.kind == 'document' and item.id != job.target_id):
            problem(404, '文档来源不可用')
        if item.extraction_status in ('ready', 'partial') and item.parser_version == PARSER_VERSION:
            return attachment_dto(item)
        # Each parse attempt gets a new revision, even after worker interruption.
        item.extraction_revision += 1
        revision, checksum = item.extraction_revision, item.sha256
        item.extraction_status, item.parser_version, item.extraction_info = 'processing', PARSER_VERSION, {}
        name = item.name
        from app.tasks.feedback_state import update_feedback
        update_feedback(job, 'parsing', '')
        job.phase, job.updated_at = 'document', now()
    path = context.settings.media_dir / identifier
    try:
        def digest_file():
            with path.open('rb') as source:
                return hashlib.file_digest(source, 'sha256').hexdigest()
        actual = await asyncio.to_thread(digest_file)
        if actual != checksum:
            raise ValueError('原文件校验失败，请重新上传')
        result = await parse_process(path, Path(name).suffix.lower())
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
        return attachment_dto(item)
