import json
from fastapi import HTTPException
from langchain.tools import ToolRuntime, tool
from paa_server.modules.attachments.models import Attachment
from paa_server.tasks.context import RunContext
from paa_server.tasks.lease import lease


@tool
async def find_documents(query: str, runtime: ToolRuntime[RunContext], attachment_id: str | None = None, start: int = 0) -> str:
    """List authorized current-conversation/confirmed-source documents. To search a
    document's full extracted text, pass its real attachment_id and query; returns
    at most 3 matching located chunks. start paginates by ordinal or directory offset.
    """
    from paa_server.modules.attachments.documents import agent_attachment, attachment_dto, chunk_page, document_statement
    context = runtime.context
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        if attachment_id:
            try:
                item = await agent_attachment(db, attachment_id, actor, job)
            except HTTPException:
                return '文件不属于本次授权来源或已删除。'
            context.document_versions[item.id] = item.extraction_revision
            result = await chunk_page(db, item, max(0, min(start, 2000)), 3, query)
            return document_tool_result(context, item, result, job)
        statement = await document_statement(db, actor, job)
        if query:
            statement = statement.where(Attachment.name.icontains(query[:120], autoescape=True))
        offset = max(0, min(start, 10000))
        items = list((await db.scalars(statement.order_by(Attachment.created_at, Attachment.id).offset(offset).limit(11))).all())
        return json.dumps({'items': [attachment_dto(item) for item in items[:10]], 'nextCursor': offset + 10 if len(items) > 10 else None}, ensure_ascii=False)


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
    nextCursor until null for complete coverage; cite only returned citation tokens.
    """
    from paa_server.modules.attachments.documents import agent_attachment, chunk_page
    context = runtime.context
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        try:
            item = await agent_attachment(db, attachment_id, actor, job)
        except HTTPException:
            return '文件不属于本次授权来源或已删除。'
        context.document_versions[item.id] = item.extraction_revision
        return document_tool_result(context, item, await chunk_page(db, item, max(0, min(start, 2000))), job)
