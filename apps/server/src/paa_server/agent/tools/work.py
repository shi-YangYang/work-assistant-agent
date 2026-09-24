import hashlib
import json
from langchain.tools import ToolRuntime, tool
from paa_server.agent.tools.common import clip, referenced_record
from paa_server.modules.attachments.models import Attachment
from paa_server.modules.messages.models import Message
from paa_server.modules.work.models import ProgressDraft, WorkItem
from paa_server.modules.work.projection import work_for_model as business_work_for_model
from paa_server.modules.work.schemas import Progress
from paa_server.security.access import inherit as business_inherit, require as business_require, valid as business_valid
from paa_server.security.ownership import owned
from paa_server.tasks.context import RunContext
from paa_server.tasks.lease import lease
from sqlalchemy import select
from typing import Literal


@tool
async def find_work_items(query: str, runtime: ToolRuntime[RunContext], status: Literal['', 'in_progress', 'blocked', 'done'] = '', cursor: str = '') -> str:
    """Find the current user's confirmed work, including administrators' own work.

    query matches literal text in title, summary, blocker and nextStep, just like
    the work list. Use query='' for a status/list question.
    status filters current business status. Returns items and nextCursor, up to
    20 items/page; follow nextCursor with unchanged filters for complete coverage.
    An empty first page with no nextCursor definitively has no matching work.
    It does not mean the user has done no work or has no unconfirmed messages.
    """
    from paa_server.core.pagination import cursor_decode, cursor_encode
    from paa_server.modules.work.queries import status_filter
    status_filter(status)
    boundary = cursor_decode(cursor) if cursor else None
    context = runtime.context
    async with context.sessions.begin() as db:
        live, actor = await lease(db, context)
        statement = select(WorkItem).where(WorkItem.deleted.is_(False), WorkItem.owner_id == actor.id, WorkItem.company_id == actor.company_id)
        from paa_server.modules.work.queries import work_search
        if query.strip():
            statement = statement.where(work_search(query[:120]))
        if status:
            statement = statement.where(WorkItem.content['status'].astext == status)
        visible = []
        # Authorization can hide an entire batch. Scan to an actual page/end,
        # so a hidden or irrelevant recent row cannot cause a false empty result.
        while len(visible) <= 20:
            page = statement
            if boundary:
                stamp, identifier = boundary
                page = page.where((WorkItem.updated_at < stamp) | ((WorkItem.updated_at == stamp) & (WorkItem.id < identifier)))
            rows = list((await db.scalars(page.order_by(WorkItem.updated_at.desc(), WorkItem.id.desc()).limit(100))).all())
            for row in rows:
                if await business_valid(db, actor, row.access, retained=True):
                    visible.append(row)
                    if len(visible) > 20:
                        break
            if len(rows) < 100 or len(visible) > 20:
                break
            boundary = rows[-1].updated_at, rows[-1].id
        items, selected, size = [], [], 0
        for row in visible[:20]:
            previous_access = live.access
            item = await business_work_for_model(db, actor, live, row)
            item_size = len(json.dumps(item, ensure_ascii=False, default=str))
            # Return whole records and a continuation, never cut JSON mid-field.
            if items and size + item_size > 6000:
                live.access = previous_access
                break
            items.append(item)
            selected.append(row)
            size += item_size
        context.read_versions.update({w.id: w.revision for w in selected})
        context.own_work_searched = True
        live.result = {**live.result, 'ownWorkSearched': True}
        next_cursor = cursor_encode(selected[-1].updated_at, selected[-1].id) if len(visible) > len(selected) else None
        return json.dumps({'scope': 'self', 'filters': {'query': query[:120], 'status': status}, 'items': items, 'nextCursor': next_cursor}, ensure_ascii=False, default=str)


@tool
async def get_work_item(work_id: str, runtime: ToolRuntime[RunContext]) -> str:
    """Read current confirmed progress and its authoritative revision for this employee."""
    async with runtime.context.sessions.begin() as db:
        live, actor = await lease(db, runtime.context)
        item = await referenced_record(db, WorkItem, work_id, actor)
        if item is None:
            return '工作记录不存在或无权查看。请使用 find_work_items 返回的工作 ID，不要猜测 ID。'
        await business_require(db, actor, item.access, retained=True)
        runtime.context.read_versions[item.id] = item.revision
        return clip(await business_work_for_model(db, actor, live, item))


@tool
async def propose_progress(title: str, summary: str, status: Literal['in_progress', 'blocked', 'done'], blocker: str, next_step: str, runtime: ToolRuntime[RunContext], work_id: str | None = None) -> str:
    """Propose progress for employee confirmation; never confirms work.

    Use blocked when a dependency prevents the next step, in_progress for ongoing
    work, and done only when the entire work is finished. For new work, work_id
    can be omitted or JSON null. For existing work, use only an ID
    returned by find_work_items or get_work_item. blocker contains only unresolved
    dependencies; use an empty string when none remain and describe any resolved
    blocker in summary instead.
    """
    content = Progress(title=title, summary=summary, status=status, blocker=blocker, nextStep=next_step).model_dump(mode='json', exclude_unset=True)
    # Some compatible providers serialize an optional null as a string. These
    # empty sentinels cannot identify a stored work item; other IDs stay checked.
    if isinstance(work_id, str) and work_id.strip() in ('', 'null'):
        work_id = None
    context = runtime.context
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        if job.kind != 'message':
            return '报告任务不能修改进展建议。'
        if actor.role == 'admin' and job.access.get('team'):
            return '团队查询请使用 propose_followup，并提供实际读取的业务关联；纯问答不要创建建议。'
        message = await owned(db, Message, job.target_id, actor, lock=True)
        if not message.text and await db.scalar(select(Attachment.id).where(Attachment.message_id == message.id, Attachment.kind == 'document', Attachment.deleted.is_(False)).limit(1)):
            return '员工仅发送文件，尚未说明处理意图。请先概览已读范围并询问，暂不提出工作进展。'
        work = await referenced_record(db, WorkItem, work_id, actor) if work_id is not None else None
        if work_id is not None and work is None:
            return '工作记录不存在或无权查看。新工作请省略 work_id；关联已有工作请先查询并使用真实工作 ID。'
        if work:
            await business_require(db, actor, work.access, retained=True)
        if work and context.read_versions.get(work.id) != work.revision:
            return '工作记录尚未读取或已被员工更新，请重新读取并核对后提出建议。'
        key = f'{job.id}:{hashlib.sha256(json.dumps([content, work_id], sort_keys=True).encode()).hexdigest()}'
        prior = await db.scalar(select(ProgressDraft).where(ProgressDraft.tool_key == key))
        if prior:
            return clip({'draftId': prior.id, 'status': prior.status})
        if len(message.suggestions) >= 20:
            return '本轮建议已达到 20 项，请结束并等待员工确认。'
        draft = ProgressDraft(company_id=actor.company_id, owner_id=actor.id, message_id=message.id, content=content, work_id=work.id if work else None, base_revision=work.revision if work else None, tool_key=key)
        business_inherit(actor, draft, job, message, *([work] if work else []))
        db.add(draft)
        await db.flush()
        # Public original snapshot never changes when the employee edits the private draft.
        message.suggestions = [*message.suggestions, {'id': draft.id, 'content': content, 'workId': draft.work_id}]
        return clip({'draftId': draft.id, 'status': 'pending', 'message': '等待员工确认'})
