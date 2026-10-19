import json
from fastapi import HTTPException
from langchain.tools import ToolRuntime, tool
from app.modules.attachments.models import Attachment
from app.tasks.context import InputChanged, RunContext
from app.tasks.lease import lease


SEARCH_BATCHES = 3


async def document_directory(db, actor, job, *, query='', start=0):
    from app.modules.attachments.documents import agent_attachment, document_reference, document_statement
    statement = await document_statement(db, actor, job)
    if query:
        statement = statement.where(Attachment.name.icontains(query[:120], autoescape=True))
    offset = max(0, min(start, 10000))
    items = list((await db.scalars(statement.order_by(Attachment.created_at, Attachment.id).offset(offset).limit(11))).all())
    visible = []
    for item in items[:10]:
        try:
            await agent_attachment(db, item.id, actor, job)
            visible.append(document_reference(item))
        except HTTPException:
            continue
    return {'items': visible, 'nextCursor': offset + 10 if len(items) > 10 else None}


async def unavailable_reference(db, actor, job):
    # Deliberately identical for unknown and unauthorized IDs. Only the normal
    # authorized directory helps the planner recover; never inspect the bad ID.
    return json.dumps({
        'error': 'document_reference_unavailable',
        'message': '文件不属于本次授权来源或当前不可用。单个 ID 查询失败不能证明原文件已被删除。',
        'availableDocuments': await document_directory(db, actor, job),
        'nextStep': '从 availableDocuments 选择与请求相符的真实附件 ID；不能猜测 ID 或自动改选其它材料。',
    }, ensure_ascii=False)


@tool
async def find_documents(query: str, runtime: ToolRuntime[RunContext], attachment_id: str | None = None, start: int = 0) -> str:
    """Without attachment_id, query filters authorized filenames (empty lists files).
    With a real ID, query searches text, including unextracted tails: up to 3
    source batches and 3 ordered matches, with bounded later-match/nearby text.
    In each searched range, exact phrase first; otherwise whitespace terms match
    any (quotes stay exact). Context text shares the 12000-character return limit.
    searchScope gives mode/range; nextCursor resumes omitted matches. An empty batch
    does not prove full-source absence. Matches are text, not whole-file coverage.
    Directory entries provide original/conversion formats and readPages for pictures.
    """
    context = runtime.context
    if attachment_id:
        return await read_document_result(context, attachment_id, start=start, query=query, limit=3)
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        result = await document_directory(db, actor, job, query=query, start=start)
        if query and not result['items'] and not start:
            result.update(searchScope='filename', availableDocuments=await document_directory(db, actor, job),
                          nextStep='未匹配到文件名不代表正文无此信息。选择真实附件 ID 后，用 query 搜索该文件正文。')
        return json.dumps(result, ensure_ascii=False)


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
        result['reuseScope'] = '以上同内容附件复用本次返回的分段；未返回部分仍未读取，附件份数不等于业务记录数。'
    if rows:
        result['positionBasis'] = '原文位置用 location；ordinal 是从 0 开始的提取分片游标，不是原文段落号。'
    info = item.extraction_info or {}
    returned = {row['ordinal'] for row in rows}
    total = info.get('chunks', 0)
    cumulative = {entry[2] for entry in context.document_reads.values()
                  if entry[0] == item.id and entry[1] == item.extraction_revision}
    delivered = {entry[2] for entry in job.result.get('documentTextProvided', {}).values()
                 if entry[0] == item.id and entry[1] == item.extraction_revision}
    limits = []
    if len(cumulative) < total:
        limits.append('未返回的文字不能用本次匹配或抽样结果概括。')
    if not info.get('sourceComplete'):
        limits.append('原文件仍有未提取范围。')
    if info.get('convertedFormat'):
        limits.append('仅核对转换后文字；原件图形、版式和嵌入内容是否丢失未核验。')
    elif info.get('hasVisuals'):
        limits.append('此文字回执不含图片，页图读取另计。')
    result['readScope'] = {
        'returnedChunks': len(returned), 'extractedChunks': total,
        'allExtractedTextReturned': bool(total) and len(returned) == total,
        'returnedChunksThisTask': len(cumulative),
        'unreturnedExtractedChunksThisTask': max(0, total - len(cumulative)),
        'providedChunksBeforeThisCall': len(delivered),
        'textBasis': 'converted_text' if info.get('convertedFormat') else 'extracted_text',
        'pageImagesIncluded': False,
        'limitations': limits,
    }
    if structure := table_structure_reference(info):
        result['tableStructure'] = structure
    job.result = {**job.result, 'documentReads': context.document_reads, 'documentReadAliases': aliases}
    return json.dumps(result, ensure_ascii=False)


async def read_document_result(context, attachment_id, *, start=0, query='', limit=40, view='text', pages=None, resolution='normal', sheet=''):
    from app.modules.attachments.documents import agent_attachment, chunk_page, document_reference
    async with context.sessions() as db:
        job, actor = await lease(db, context)
        try:
            await agent_attachment(db, attachment_id, actor, job)
        except HTTPException:
            return await unavailable_reference(db, actor, job)
    if view == 'pages':
        from app.agent.context.document_input import request_pages
        return json.dumps(await request_pages(context, attachment_id, pages or [1], resolution=resolution, sheet=sheet), ensure_ascii=False)
    if view != 'text':
        return json.dumps({'error': 'invalid_view', 'message': 'view 只能为 text 或 pages'})
    from app.tasks.processing.document_ranges import ensure_range
    cursor = max(0, min(int(start), 10_000_000))
    searched = []
    batches = SEARCH_BATCHES if query else 1
    for batch in range(batches):
        try:
            prepared = await ensure_range(context, attachment_id, cursor)
        except InputChanged:
            raise
        except (ValueError, OSError):
            prepared = {'rangeError': '部分内容暂时无法读取，请稍后重试'}
        async with context.sessions.begin() as db:
            job, actor = await lease(db, context)
            item = await agent_attachment(db, attachment_id, actor, job)
            context.document_versions[item.id] = item.extraction_revision
            result = await chunk_page(db, item, cursor, limit, query)
            result['attachment'] = document_reference(item)
            warning = prepared.get('rangeError') or prepared.get('error')
            following = result['nextCursor']
            if query:
                scope = result['searchScope']
                end = scope['toOrdinal']
                if end > cursor:
                    searched.append([cursor, end])
                reason = ('matches' if result['items'] else 'range_error' if warning else
                          'source_end' if following is None else 'no_progress' if following <= cursor else
                          'batch_limit' if batch + 1 == batches else None)
                scope.update(fromOrdinal=max(0, min(int(start), 10_000_000)), ranges=searched,
                             batches=batch + 1, stopReason=reason)
                if reason == 'no_progress':
                    warning = '后续范围暂时无法读取；本次查找已停止，不能据此判断全文没有匹配。'
                if reason is None:
                    cursor = following
                    continue
            if warning:
                result['scopeWarning'] = warning
                if not result['items']:
                    if query:
                        result['retryCursor'] = cursor
                    result['nextCursor'] = None
            return await document_tool_result(db, context, item, result, job)


@tool
async def read_document(attachment_id: str, start: int, runtime: ToolRuntime[RunContext], view: str = 'text', pages: list[int] | None = None, resolution: str = 'normal', sheet: str = '') -> str:
    """Read missing source text from a zero-based fragment ordinal (up to 40
    chunks/12000 chars). readScope describes returned text; sourceComplete describes
    extraction. nextCursor resumes reading if needed; null ends this traversal only.
    For layout, scans or charts use view=pages, pages=[1,2] (1-based, max 4),
    resolution=normal or detail; XLSX requires sheet. Page pixels reach the next
    model request directly. Exhaustive requests require the requested range.
    """
    return await read_document_result(runtime.context, attachment_id, start=start, view=view, pages=pages, resolution=resolution, sheet=sheet)
