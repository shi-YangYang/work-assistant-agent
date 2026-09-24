import hashlib
import json
from fastapi import HTTPException
from langchain.tools import ToolRuntime, tool
from app.agent.tools.common import clip, explicit_followup, referenced_record
from app.modules.messages.models import Message
from app.modules.team.agent_queries import find_members as business_find_members, query_business as business_query_business
from app.modules.team.sources import canonical_token as business_canonical_token, read_source as business_read_source
from app.modules.work.models import ProgressDraft, WorkItem
from app.modules.work.schemas import Progress
from app.security.access import inherit as business_inherit, merge_access as business_merge_access, require as business_require, resolve as business_resolve, scope as business_scope
from app.security.ownership import owned
from app.tasks.context import RunContext
from app.tasks.lease import lease
from sqlalchemy import select
from typing import Literal


@tool
async def find_team_members(query: str, runtime: ToolRuntime[RunContext]) -> str:
    """Match employee names within the administrator's company. Multiple matches
    require clarification; IDs returned here are filters, not write authority.
    """
    async with runtime.context.sessions.begin() as db:
        job, actor = await lease(db, runtime.context)
        try:
            return json.dumps(await business_find_members(db, actor, job, query), ensure_ascii=False)
        except HTTPException as error:
            return json.dumps({'error': error.detail}, ensure_ascii=False)


@tool
async def query_team_business(runtime: ToolRuntime[RunContext], kind: Literal['work', 'report'] = 'work', employee_ids: list[str] | None = None, query: str = '', status: Literal['', 'in_progress', 'blocked', 'done'] = '', period: Literal['current', 'recent', 'this_week', 'last_week', 'custom'] = 'current', start: str = '', end: str = '', cursor: str = '', employee_name: str = '') -> str:
    """Query employee confirmed work or submitted report versions. current reads
    current status; other periods read changes inside company-local dates. recent
    means the last 7 days. Custom dates are YYYY-MM-DD. Empty employee_ids means
    all employees. At most 20 details/page; total/statusCounts describe the full
    matching authorized set. Pass returned nextCursor with unchanged filters.
    For one employee named by the user, pass employee_name directly instead of
    find_team_members then querying again. Unique matches resolve and query in
    one call; absent/ambiguous names return candidates without reading work.
    Never combine employee_name with employee_ids. Returned employee.id can be
    reused for pagination; use find_team_members for directory questions.
    """
    async with runtime.context.sessions.begin() as db:
        job, actor = await lease(db, runtime.context)
        try:
            if employee_name.strip():
                if employee_ids:
                    return json.dumps({'error': '姓名与员工 ID 不能同时指定，请选择一种查询方式。'}, ensure_ascii=False)
                members = await business_find_members(db, actor, job, employee_name.strip())
                if members['total'] != 1:
                    return json.dumps({'state': 'clarification' if members['total'] else 'not_found', 'members': members, 'message': '请明确具体员工。' if members['total'] else '未找到该员工。'}, ensure_ascii=False)
                employee_ids = [members['items'][0]['id']]
            result = await business_query_business(db, actor, job, kind=kind, employee_ids=employee_ids, query=query, status=status, period=period, start=start, end=end, cursor=cursor)
            if employee_name.strip():
                result['employee'] = members['items'][0]
            return json.dumps(result, ensure_ascii=False)
        except HTTPException as error:
            return json.dumps({'error': error.detail}, ensure_ascii=False)


@tool
async def read_team_source(token: str, runtime: ToolRuntime[RunContext], child_id: str = '', start: int = 0) -> str:
    """Read an actual versioned team source returned by query_team_business. For
    original text, pass a sourceMessageIds entry as child_id and its parent token.
    For document text, pass a document attachment child_id under the message token
    and start as its zero-based chunk ordinal. No OCR, vision or ASR is started.
    Never guess IDs. Cite only returned [[business:...]] tokens.
    """
    async with runtime.context.sessions.begin() as db:
        job, actor = await lease(db, runtime.context)
        try:
            return json.dumps(await business_read_source(db, actor, job, token, child_id, start), ensure_ascii=False)
        except HTTPException as error:
            return json.dumps({'error': error.detail}, ensure_ascii=False)


@tool
async def propose_followup(title: str, summary: str, status: Literal['in_progress', 'blocked', 'done'], blocker: str, next_step: str, source_tokens: list[str], runtime: ToolRuntime[RunContext], work_id: str | None = None) -> str:
    """Prepare a suggestion ONLY when the administrator asks for a draft/proposal.
    Explicitly requesting a saved follow-up uses execute_business_action instead.
    First find_work_items to avoid duplicates. Link 1-20 exact work/report token
    fields (not [[business:...]] citation strings). Employees remain sources, never
    assignees. Updating existing own work requires its freshly-read work_id.
    """
    content = Progress(title=title, summary=summary, status=status, blocker=blocker, nextStep=next_step).model_dump()
    context = runtime.context
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        if actor.role != 'admin' or job.kind != 'message':
            return '当前账号或任务不能创建督办建议。'
        message = await owned(db, Message, job.target_id, actor)
        intent = message.text + '\n' + message.transcript
        if not explicit_followup(intent):
            return '用户尚未明确要求创建或更新本人督办；请只回答问题。'
        if not context.own_work_searched:
            return '请先查询本人已有工作，确认这是新增还是更新。'
        if not 1 <= len(source_tokens) <= 20:
            return '请选择 1～20 个实际读取的工作或已提交报告来源。'
        links = []
        for raw_token in dict.fromkeys(source_tokens):
            token = business_canonical_token(raw_token)
            evidence = job.access.get('reads', {}).get(token)
            if not evidence or evidence.get('type') not in ('work', 'report'):
                return '关联来源未被读取或不是工作／已提交报告，请先查询。'
            try:
                await business_resolve(db, actor, evidence, latest=True)
            except HTTPException:
                return '关联来源已变化或无权查看，请重新查询后提出建议。'
            links.append({'token': token, 'evidence': evidence})
        work = await referenced_record(db, WorkItem, work_id, actor) if work_id and work_id != 'null' else None
        if work_id and work_id != 'null' and not work:
            return '只能更新本人工作，请使用本人查询返回的 ID。'
        if work:
            await business_require(db, actor, work.access, retained=True)
        if work and context.read_versions.get(work.id) != work.revision:
            return '本人事项尚未读取或已更新，请先重新读取。'
        key = f'{job.id}:' + hashlib.sha256(json.dumps([content, work_id, sorted(source_tokens)], sort_keys=True).encode()).hexdigest()
        existing = await db.scalar(select(ProgressDraft).where(ProgressDraft.tool_key == key))
        if existing:
            return clip({'draftId': existing.id, 'status': existing.status})
        if len(message.suggestions) >= 20:
            return '本轮建议已达到 20 项，请等待确认。'
        draft = ProgressDraft(company_id=actor.company_id, owner_id=actor.id, message_id=message.id, content=content, work_id=work.id if work else None, base_revision=work.revision if work else None, tool_key=key, business_links=links, access=job.access)
        business_inherit(actor, draft, message, *([work] if work else []))
        db.add(draft)
        await db.flush()
        message.access = business_merge_access(message.access or business_scope(actor), job.access)
        message.suggestions = [*message.suggestions, {'id': draft.id, 'content': content, 'workId': draft.work_id}]
        return clip({'draftId': draft.id, 'status': 'pending', 'message': '本人督办建议已准备，等待管理员确认；未向员工派单。'})


TEAM_TOOLS = [find_team_members, query_team_business, read_team_source, propose_followup]
