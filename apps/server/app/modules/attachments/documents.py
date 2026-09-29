import re
from app.core.errors import problem
from app.modules.attachments.models import Attachment, DocumentChunk
from app.modules.messages.models import Message
from app.modules.work.models import WorkItem, WorkRevision
from app.security.ownership import owned
from pathlib import Path
from sqlalchemy import select

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
        from app.modules.operations.mutations.publication import shared_attachment, published_attachment
        if item.owner_id == actor.id and await published_attachment(db, item):
            return item
        if item.owner_id != actor.id and await shared_attachment(db, actor, item):
            return item
        message = await owned(db, Message, item.message_id, actor, read=True)
        if message.owner_id != item.owner_id:
            problem(404, '附件来源不可用')
    return item


async def document_statement(db, actor, job):
    current = await owned(db, Message, job.target_id, actor) if job.kind == 'message' else None
    revisions = (await db.scalars(select(WorkRevision).join(WorkItem, WorkItem.id == WorkRevision.work_id).where(WorkItem.deleted.is_(False), WorkRevision.owner_id == actor.id, WorkRevision.company_id == actor.company_id, *([WorkRevision.id.in_(job.result.get('sourceIds', []))] if job.kind == 'report' else [])))).all()
    sources = {mid for revision in revisions for mid in revision.source_ids}
    published = {aid for revision in revisions for aid in revision.publication.get('attachmentIds', [])}
    scope = Message.id.in_(sources)
    if current:
        scope = scope | (Message.conversation_id == current.conversation_id)
    return select(Attachment).join(Message, Message.id == Attachment.message_id).where(Attachment.owner_id == actor.id, Attachment.company_id == actor.company_id, Attachment.deleted.is_(False), Attachment.kind == 'document', (Message.deleted.is_(False) & scope) | Attachment.id.in_(published))


async def agent_attachment(db, identifier, actor, job):
    # Admin team browsing never grants the assistant cross-employee access.
    item = await owned(db, Attachment, identifier, actor)
    if item.kind != 'document' or not item.message_id:
        problem(404, '文件不可用或尚未发送')
    from app.modules.operations.mutations.publication import published_attachment
    if await published_attachment(db, item, revision_ids=job.result.get('sourceIds', []) if job.kind == 'report' else None):
        return item
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


async def chunk_page(db, item, start=0, limit=3, query=''):
    statement = select(DocumentChunk).where(DocumentChunk.attachment_id == item.id, DocumentChunk.revision == item.extraction_revision, DocumentChunk.ordinal >= start)
    if query:
        statement = statement.where(DocumentChunk.text.icontains(query[:120], autoescape=True))
    rows = list((await db.scalars(statement.order_by(DocumentChunk.ordinal).limit(limit + 1))).all())
    return {'attachment': attachment_dto(item), 'items': [{'ordinal': row.ordinal, 'location': row.location, 'text': row.text} for row in rows[:limit]], 'nextCursor': rows[limit - 1].ordinal + 1 if len(rows) > limit else None}


CITATION = re.compile(r'\[\[file:([^\]\n]+)\]\]')


async def verified_citations(db, context, answer):
    from app.tasks.lease import lease
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


async def material_coverage(db, actor, job, documents, reads):
    """Keep extracted-text reads distinct from files supplied for computation."""
    from app.modules.executions.models import SandboxExecution
    executions = (await db.scalars(select(SandboxExecution).where(SandboxExecution.job_id == job.id,
        SandboxExecution.owner_id == actor.id, SandboxExecution.company_id == actor.company_id,
        SandboxExecution.state == 'succeeded'))).all()
    coverage, legacy = [], []
    for document in documents:
        read = len({entry[2] for entry in reads.values() if entry[0] == document.id and entry[1] == document.extraction_revision})
        total = document.extraction_info.get('chunks', 0)
        if document.extraction_status == 'failed':
            detail = '文字提取失败：' + document.extraction_info.get('error', '解析失败')
            old_detail = '未能使用：' + document.extraction_info.get('error', '解析失败')
        else:
            detail = f'文字工具读取 {read}/{total} 个分段'
            old_detail = f'实际读取 {read}/{total} 个文字分段'
            if document.extraction_status == 'partial':
                detail += '；文件文字仅部分可读'
                old_detail += '；文件仅部分可读'
        related = [row for row in executions if any(source.get('kind') == 'attachment' and source.get('id') == document.id
            and source.get('revision') == document.extraction_revision and source.get('sha256') == document.sha256 for source in row.sources)]
        direct = any(ref.get('attachment_id') == document.id for row in related for ref in row.result.get('inputRefs', []))
        if direct:
            detail += '；原文件已提供给代码执行，具体读取范围未单独记录'
        elif related:
            detail += '；列为代码执行的关联来源，不能据此认定本轮已读取原文件'
        coverage.append(document.name + '：' + detail)
        legacy.append(document.name + '：' + old_detail)
    return coverage, legacy


def append_material_coverage(answer, coverage, legacy):
    """Replace only an identical terminal scope note, preserving answer prose."""
    normalize = lambda value: re.sub(r'\s+', '', value)
    equivalents = {normalize('\n'.join(lines)) for lines in (coverage, legacy)}
    while True:
        prefix, separator, tail = answer.rpartition('\n\n材料范围：')
        if not separator and answer.startswith('材料范围：'):
            prefix, separator, tail = '', '材料范围：', answer[len('材料范围：'):]
        if not separator or normalize(tail) not in equivalents:
            break
        answer = prefix.rstrip()
    return answer + '\n\n材料范围：\n' + '\n'.join(coverage)
