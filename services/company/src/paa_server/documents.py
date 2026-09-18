"""Private document identity, extraction publication and authorized bounded reads."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from sqlalchemy import delete, select

from .document_parser import MEMORY_BYTES, PARSER_VERSION
from .models import Attachment, DocumentChunk, Job, Message, WorkItem, WorkRevision, now
from .service import owned, problem

DOCUMENT_TYPES = {
    '.pdf': 'application/pdf',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    '.txt': 'text/plain', '.json': 'application/json', '.md': 'text/markdown', '.csv': 'text/csv',
}


def safe_name(name):
    basename = re.sub(r'[\x00-\x1f\x7f]', '', (name or 'attachment').replace('\\', '/').split('/')[-1]) or 'attachment'
    suffix = Path(basename).suffix[:16]
    return basename if len(basename) <= 180 else basename[:180 - len(suffix)] + suffix


def document_type(name, supplied_mime):
    suffix = Path(name).suffix.lower()
    if suffix in DOCUMENT_TYPES:
        permitted = {DOCUMENT_TYPES[suffix], 'application/octet-stream', '', 'application/zip' if suffix in ('.docx', '.pptx', '.xlsx') else 'text/plain'}
        if suffix in ('.json', '.csv', '.md'):
            permitted |= {'text/json', 'application/csv', 'application/vnd.ms-excel', 'text/x-markdown'}
        if (supplied_mime or '').split(';')[0].lower() not in permitted:
            problem(415, '文件类型与扩展名不一致，请重新导出后上传')
        return DOCUMENT_TYPES[suffix]
    if suffix in ('.doc', '.ppt', '.xls', '.xlsm', '.docm', '.pptm'):
        problem(415, '暂不支持旧版 Office 或含宏格式；请转换为 PDF、DOCX、PPTX、XLSX 或 CSV')
    return None


def attachment_dto(a):
    return {'id': a.id, 'kind': a.kind, 'name': a.name, 'size': a.size, 'mime': a.mime, 'duration': a.duration, 'url': f'/api/v1/uploads/{a.id}/content', 'previewUrl': f'/api/v1/uploads/{a.id}/preview' if a.kind in ('image', 'audio') else None, 'image': a.extraction_info if a.kind == 'image' else None, 'extraction': {'status': a.extraction_status, 'revision': a.extraction_revision, 'parserVersion': a.parser_version, **(a.extraction_info or {})} if a.kind == 'document' else None}


async def visible_attachment(db, identifier, actor, *, lock=False):
    item = await owned(db, Attachment, identifier, actor, read=True, lock=lock)
    if not item.message_id:
        if item.owner_id != actor.id:
            problem(404, '附件尚未发送或无权查看')
    else:
        message = await owned(db, Message, item.message_id, actor, read=True)
        if message.owner_id != item.owner_id:
            problem(404, '附件来源不可用')
    return item


async def document_statement(db, actor, job):
    current = await owned(db, Message, job.target_id, actor) if job.kind == 'message' else None
    revisions = (await db.scalars(select(WorkRevision).join(WorkItem, WorkItem.id == WorkRevision.work_id).where(WorkItem.deleted.is_(False), WorkRevision.owner_id == actor.id, WorkRevision.company_id == actor.company_id, *([WorkRevision.id.in_(job.result.get('sourceIds', []))] if job.kind == 'report' else [])))).all()
    sources = {mid for revision in revisions for mid in revision.source_ids}
    scope = Message.id.in_(sources)
    if current:
        scope = scope | (Message.conversation_id == current.conversation_id)
    return select(Attachment).join(Message, Message.id == Attachment.message_id).where(Attachment.owner_id == actor.id, Attachment.company_id == actor.company_id, Attachment.deleted.is_(False), Attachment.kind == 'document', Message.deleted.is_(False), scope)


async def agent_attachment(db, identifier, actor, job):
    # Admin team browsing never grants the assistant cross-employee access.
    item = await owned(db, Attachment, identifier, actor)
    if item.kind != 'document' or not item.message_id:
        problem(404, '文件不可用或尚未发送')
    message = await owned(db, Message, item.message_id, actor)
    current = await owned(db, Message, job.target_id, actor) if job.kind == 'message' else None
    if not current or message.conversation_id != current.conversation_id:
        source = await db.scalar(select(WorkRevision.id).join(WorkItem, WorkItem.id == WorkRevision.work_id).where(WorkRevision.company_id == actor.company_id, WorkRevision.owner_id == actor.id, WorkItem.deleted.is_(False), WorkRevision.source_ids.contains([message.id])).limit(1))
        if source is None:
            problem(404, '文件不属于当前会话或本人已确认工作来源')
        if job.kind == 'report':
            bound = await db.scalar(select(WorkRevision.id).where(WorkRevision.id.in_(job.result.get('sourceIds', [])), WorkRevision.owner_id == actor.id, WorkRevision.company_id == actor.company_id, WorkRevision.source_ids.contains([message.id])).limit(1))
            if bound is None:
                problem(404, '文件不属于本次报告的已确认来源')
    return item


async def parse_process(path, suffix, *, timeout=60, entrypoint=None, max_output=2 * 1024 * 1024):
    """No credentials/config inherited, bounded pipe, cancellation always reaps child."""
    process = await asyncio.create_subprocess_exec(sys.executable, '-I', str(entrypoint or Path(__file__).with_name('document_parser.py')), str(path), suffix, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env={'LANG': 'C.UTF-8', **({'SYSTEMROOT': os.environ['SYSTEMROOT']} if 'SYSTEMROOT' in os.environ else {})})
    memory_exceeded = False
    async def monitor_memory():
        nonlocal memory_exceeded
        if sys.platform != 'darwin':
            return
        while process.returncode is None:
            probe = await asyncio.create_subprocess_exec('/bin/ps', '-o', 'rss=', '-p', str(process.pid), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            try:
                raw, _ = await asyncio.wait_for(probe.communicate(), 2)
            finally:
                if probe.returncode is None:
                    probe.kill()
                await probe.wait()
            if raw.strip() and int(raw.strip()) * 1024 > MEMORY_BYTES:
                memory_exceeded = True
                if process.returncode is None:
                    process.kill()
                return
            await asyncio.sleep(.1)
    memory_task = asyncio.create_task(monitor_memory())
    def monitor_finished(task):
        if not task.cancelled() and task.exception() and process.returncode is None:
            process.kill()
    memory_task.add_done_callback(monitor_finished)
    async def receive():
        output = bytearray()
        while block := await process.stdout.read(65536):
            output.extend(block)
            if len(output) > max_output:
                raise ValueError('文档提取结果超出限制，请拆分文件')
        await process.wait()
        if process.returncode or memory_exceeded:
            raise ValueError('文档超出解析资源限制或解析进程中断，请拆分后重试')
        return json.loads(output)
    try:
        return await asyncio.wait_for(receive(), timeout)
    except asyncio.TimeoutError:
        return {'status': 'failed', 'chunks': [], 'info': {'error': '文档解析超过 60 秒，请拆分文件后重试'}}
    except (ValueError, OSError) as error:
        return {'status': 'failed', 'chunks': [], 'info': {'error': str(error) if isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError) else '解析进程未返回有效结果，请重试'}}
    finally:
        memory_task.cancel()
        await asyncio.gather(memory_task, return_exceptions=True)
        if process.returncode is None:
            process.kill()
        await process.wait()


async def prepare_document(context, identifier):
    from .agent.harness import lease
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
        from .feedback import update_feedback
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
            from .agent.harness import LostLease
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
            from .agent.harness import InputChanged
            raise InputChanged(document=True)
        await db.execute(delete(DocumentChunk).where(DocumentChunk.attachment_id == item.id))
        for ordinal, chunk in enumerate(result['chunks']):
            db.add(DocumentChunk(company_id=item.company_id, owner_id=item.owner_id, attachment_id=item.id, revision=revision, ordinal=ordinal, location=chunk['location'], text=chunk['text']))
        item.extraction_status, item.extraction_info = result['status'], result['info']
        return attachment_dto(item)


async def chunk_page(db, item, start=0, limit=3, query=''):
    statement = select(DocumentChunk).where(DocumentChunk.attachment_id == item.id, DocumentChunk.revision == item.extraction_revision, DocumentChunk.ordinal >= start)
    if query:
        statement = statement.where(DocumentChunk.text.icontains(query[:120], autoescape=True))
    rows = list((await db.scalars(statement.order_by(DocumentChunk.ordinal).limit(limit + 1))).all())
    return {'attachment': attachment_dto(item), 'items': [{'ordinal': row.ordinal, 'location': row.location, 'text': row.text} for row in rows[:limit]], 'nextCursor': rows[limit - 1].ordinal + 1 if len(rows) > limit else None}


CITATION = re.compile(r'\[\[file:([^\]\n]+)\]\]')


async def verified_citations(db, context, answer):
    from .agent.harness import lease
    job, actor = await lease(db, context)
    citations, replacements = [], {}
    for token in CITATION.findall(answer):
        key = '[[file:' + token + ']]'
        if key in replacements:
            continue
        evidence = context.document_reads.get(token)
        if evidence is None:
            replacements[key] = '（来源未核实）'
            continue
        aid, revision, ordinal = evidence
        item = await agent_attachment(db, aid, actor, job)
        chunk = await db.scalar(select(DocumentChunk).where(DocumentChunk.attachment_id == aid, DocumentChunk.revision == revision, DocumentChunk.ordinal == ordinal))
        if item.extraction_revision != revision or chunk is None:
            replacements[key] = '（来源已变化）'
            continue
        citations.append({'attachmentId': aid, 'revision': revision, 'ordinal': ordinal, 'name': item.name, 'location': chunk.location})
        replacements[key] = f'〔{len(citations)}〕'
    for key, value in replacements.items():
        answer = answer.replace(key, value)
    return answer, citations
