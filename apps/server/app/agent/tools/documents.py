import json
from fastapi import HTTPException
from langchain.tools import ToolRuntime, tool
from app.modules.attachments.models import Attachment
from app.tasks.context import RunContext
from app.tasks.lease import lease


async def document_directory(db, actor, job, *, query='', start=0):
    from app.modules.attachments.documents import agent_attachment, attachment_dto, document_statement
    statement = await document_statement(db, actor, job)
    if query:
        statement = statement.where(Attachment.name.icontains(query[:120], autoescape=True))
    offset = max(0, min(start, 10000))
    items = list((await db.scalars(statement.order_by(Attachment.created_at, Attachment.id).offset(offset).limit(11))).all())
    visible = []
    for item in items[:10]:
        try:
            await agent_attachment(db, item.id, actor, job)
            visible.append(attachment_dto(item))
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
    """Without attachment_id, list authorized documents: query is ONE filename
    substring (empty lists all), NOT content keywords. To search a
    document's full extracted text, pass its real attachment_id and query; returns
    at most 3 matching located chunks. start paginates by ordinal or directory offset.
    Directory metadata is not document text; matching chunks support only what
    they say. Read surrounding chunks when a claim depends on missing context.
    """
    from app.modules.attachments.documents import agent_attachment, chunk_page
    context = runtime.context
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        if attachment_id:
            try:
                item = await agent_attachment(db, attachment_id, actor, job)
            except HTTPException:
                return await unavailable_reference(db, actor, job)
            context.document_versions[item.id] = item.extraction_revision
            result = await chunk_page(db, item, max(0, min(start, 2000)), 3, query)
            return document_tool_result(context, item, result, job)
        result = await document_directory(db, actor, job, query=query, start=start)
        if query and not result['items'] and not start:
            result.update(searchScope='filename', availableDocuments=await document_directory(db, actor, job),
                          nextStep='未匹配到文件名不代表正文无此信息。选择真实附件 ID 后，用 query 搜索该文件正文。')
        return json.dumps(result, ensure_ascii=False)


def document_tool_result(context, item, result, job):
    for row in result['items']:
        token = f"{item.id}:{item.extraction_revision}:{row['ordinal']}"
        context.document_reads[token] = (item.id, item.extraction_revision, row['ordinal'])
        row['citation'] = '[[file:' + token + ']]'
    job.result = {**job.result, 'documentReads': context.document_reads}
    return json.dumps(result, ensure_ascii=False)


@tool
async def read_document(attachment_id: str, start: int, runtime: ToolRuntime[RunContext]) -> str:
    """Read up to 3 real document chunks, starting at a zero-based ordinal. Use
    nextCursor until null when full coverage is needed, otherwise read only the
    relevant parts and state that scope. Keep each claim's original conditions
    and qualifiers; distinguish inference. Cite only returned citation tokens.
    """
    from app.modules.attachments.documents import agent_attachment, chunk_page
    context = runtime.context
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        try:
            item = await agent_attachment(db, attachment_id, actor, job)
        except HTTPException:
            return await unavailable_reference(db, actor, job)
        context.document_versions[item.id] = item.extraction_revision
        return document_tool_result(context, item, await chunk_page(db, item, max(0, min(start, 2000))), job)
