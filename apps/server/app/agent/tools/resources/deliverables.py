import json
from fastapi import HTTPException
from app.agent.tool_results import http_failure
from langchain.tools import ToolRuntime, tool
from pydantic import ValidationError
from app.modules.deliverables.queries import conversation_deliverables, get_deliverable, available_revision, remember_source
from app.modules.deliverables.serializers import detail, summary
from app.modules.deliverables.service import save
from app.modules.messages.models import Message
from app.security.ownership import owned
from app.tasks.context import RunContext
from app.tasks.lease import lease


def model_page(result, offset=0):
    # Preserve stable item metadata while bounding prose from long results.
    start = max(0, offset)
    length = max([len(result['body']), *(len(entry['body']) for entry in result['items'])])
    width = max(100, min(4000, 10000 // (len(result['items']) + 1)))
    return {**result, 'body': result['body'][start:start + width],
            'items': [{**entry, 'body': entry['body'][start:start + width]} for entry in result['items']],
            'nextOffset': start + width if length > start + width else None,
            'contentOffset': start, 'contentTruncated': start > 0 or length > start + width}


@tool
async def save_deliverable(title: str, body: str, runtime: ToolRuntime[RunContext], items: list[dict] | None = None, deliverable_id: str = '', expected_revision: int = 0, step: int = 1) -> str:
    """Save a private editable plan/draft/checklist/table; simple answers need no
    save. body=Markdown; items=ordered {id?,title,body?}. Omit new item IDs; preserve
    existing IDs on edit/reorder. Modify after reading latest, retain unchanged
    entries and pass deliverable_id/expected_revision. step=stable 1-8 per user
    message, including retry. Does not create work or formal reports.
    """
    context = runtime.context
    try:
        async with context.sessions.begin() as db:
            job, actor = await lease(db, context)
            if job.kind != 'message':
                return json.dumps({'state': 'failed', 'category': 'permission_denied', 'message': '只有会话可以生成个人成果'}, ensure_ascii=False)
            message = await owned(db, Message, job.target_id, actor)
            read_revision = context.deliverable_reads.get(deliverable_id, job.result.get('deliverableReads', {}).get(deliverable_id))
            item, record = await save(db, actor, message, job, {'title': title, 'body': body, 'items': items or []}, identifier=deliverable_id, expected_revision=expected_revision, read_revision=read_revision, step=step)
            context.deliverable_reads[item.id] = record.revision
            job.result = {**job.result, 'deliverableReads': {**job.result.get('deliverableReads', {}), item.id: record.revision}}
            return json.dumps({'state': 'succeeded', **model_page(await detail(db, actor, item, record))}, ensure_ascii=False)
    except HTTPException as error:
        return json.dumps(http_failure(error), ensure_ascii=False)
    except ValidationError:
        return json.dumps({'state': 'failed', 'category': 'invalid_arguments', 'message': '成果字段或长度不符合要求，请调整后重试'}, ensure_ascii=False)


@tool
async def read_deliverable(runtime: ToolRuntime[RunContext], deliverable_id: str = '', revision: int = 0, offset: int = 0) -> str:
    """Read private saved results in THIS conversation, including older plans.
    Without ID lists 20 result titles/IDs/versions per page (offset/nextOffset).
    With ID reads an exact version (0 means current). Long body and item text are paged with offset/nextOffset;
    items and stable work links preserve references across reorder/rename. Read
    latest work via get_work_item before editing linked work. Multiple links for
    one entry are real copies; don't guess which copy the user means.
    """
    context = runtime.context
    try:
        async with context.sessions.begin() as db:
            job, actor = await lease(db, context)
            message = await owned(db, Message, job.target_id, actor)
            if not deliverable_id:
                rows = await conversation_deliverables(db, actor, message.conversation_id, max(0, offset))
                results = []
                from app.security.access import valid
                for row in rows[:20]:
                    if await valid(db, actor, row.access):
                        record = await available_revision(db, actor, row.id)
                        if record:
                            remember_source(job, actor, row, record)
                            results.append(summary(row, record))
                return json.dumps({'items': results, 'nextOffset': offset + 20 if len(rows) > 20 else None}, ensure_ascii=False)
            item, record = await get_deliverable(db, actor, deliverable_id, revision or None, conversation_id=message.conversation_id)
            remember_source(job, actor, item, record)
            result = await detail(db, actor, item, record)
            from app.modules.executions.sources import remember_sources
            await remember_sources(db, job, context, [source for file in record.files or [] for source in file.get('sources', [])])
            context.deliverable_reads[item.id] = record.revision
            job.result = {**job.result, 'deliverableReads': {**job.result.get('deliverableReads', {}), item.id: record.revision}}
            result = model_page(result, offset)
            return json.dumps(result, ensure_ascii=False)
    except HTTPException as error:
        return json.dumps(http_failure(error), ensure_ascii=False)


DELIVERABLE_TOOLS = [save_deliverable, read_deliverable]
