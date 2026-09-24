import asyncio
import hashlib
import json
import time
from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.profiles import GeneralPurposeSubagentProfile, HarnessProfile, register_harness_profile
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langsmith import tracing_context
from app.agent.history import conversation_history
from app.agent.middleware import ToolBoundary
from app.agent.model import BoundedChatModel, approximate_tokens
from app.agent.policies import ADMIN_POLICY, ALLOWED_TOOLS, EXCLUDED_TOOLS, POLICY, TEAM_TOOL_NAMES, action_policy
from app.agent.tools.registry import BUSINESS_TOOLS
from app.agent.tools.team import TEAM_TOOLS
from app.db.base import now
from app.modules.messages.models import Message
from app.security.access import scope as business_scope
from app.tasks.context import RunContext
from app.tasks.lease import lease


class BusinessSummary(SummarizationMiddleware):
    pass


register_harness_profile('openai', HarnessProfile(excluded_tools=EXCLUDED_TOOLS, excluded_middleware=frozenset({'SummarizationMiddleware'}), general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)))


def build_graph(settings, checkpointer, context, model=None):
    if model is None:
        choice = (context.model_binding or {}).get(context.model_purpose) or {}
        model = BoundedChatModel(model=choice.get('model', 'unconfigured'), api_key='server-managed', max_retries=0, timeout=60, max_tokens=4000, streaming=False, use_responses_api=False, stream_usage=False)
        model._run_context = context
    graph = create_deep_agent(model, tools=BUSINESS_TOOLS + (TEAM_TOOLS if context.role == 'admin' else []), system_prompt=(ADMIN_POLICY if context.role == 'admin' else POLICY) + action_policy(context.role) + '\n' + getattr(context, 'request_clock', ''), middleware=[BusinessSummary(model, trigger=('tokens', 12000), keep=('messages', 6), token_counter=approximate_tokens), ToolBoundary()], subagents=[], backend=StateBackend(), context_schema=RunContext, checkpointer=checkpointer)
    return graph


async def invoke_harness(context, checkpointer, content, model=None, *, repair_missing_action=False):
    from app.agent.checkpoints import GuardedSaver
    async with context.sessions.begin() as db:
        live, actor = await lease(db, context)
        if not live.access:
            live.access = business_scope(actor)
        context.role = actor.role
    from app.modules.members.models import Company
    from zoneinfo import ZoneInfo
    async with context.sessions() as db:
        company = await db.get(Company, context.company_id)
        message = await db.get(Message, live.target_id) if live.kind == 'message' else None
        clock = message.created_at if message else now()
        clock_note = f"当前请求时间：{clock.astimezone(ZoneInfo(company.rules['timezone'])).isoformat()}；公司时区：{company.rules['timezone']}。相对日期以此为准；日期回复需写具体年月日。"
    context.request_clock = clock_note
    graph = build_graph(context.settings, GuardedSaver(checkpointer, context), context, model)
    async with context.sessions() as db:
        job, actor = await lease(db, context)
        # Checkpoints include pending executable tools. Never share them between jobs,
        # even for the same employee or report; history below contains business data only.
        thread = f'{actor.company_id}:{actor.id}:job:{job.id}'
        if context.model_binding is not None:
            config_digest = hashlib.sha256(json.dumps(context.model_binding, sort_keys=True).encode()).hexdigest()
            thread += f':config:{context.config_attempt}:{config_digest}'
        if job.kind == 'message':
            if context.source_revision is None:
                raise ValueError('消息输入版本缺失，无法恢复处理')
            digest = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            thread += f':input:{context.source_revision}:{digest}'
            if context.document_snapshot:
                thread += ':files:' + context.document_snapshot
    config = {'configurable': {'thread_id': thread}, 'recursion_limit': 36, 'callbacks': []}
    with tracing_context(enabled=False):
        state = await graph.aget_state(config)
        repair_id = f'completion-repair:{job.id}'
        repaired = any(m.id == repair_id for m in state.values.get('messages', []))
        if state.values and repair_missing_action and not repaired and not state.next:
            instruction = '服务端核对：用户明确要求的操作尚无工具回执，上一条仅写了文字。回看原用户请求与本轮已读材料；信息足够时调用 execute_business_action。用户委托挑选单条删除对象并确认时，应调用工具准备确认卡，不是再用文字询问。管理员明确要求新建本人督办时直接保存本人工作并关联已有真实 source_tokens。不得扩展范围，不改员工工作，不实际删除或提交；有歧义则明确说明。'
            result = await asyncio.wait_for(graph.ainvoke({'messages': [HumanMessage(id=repair_id, content=instruction)]}, config, context=context), timeout=max(0.01, 180 - (time.monotonic() - context.started)))
        elif state.values:
            # The worker already checked retry authorization and lease. Resume this
            # job's unchanged input; a completed graph needs no second external request.
            result = await asyncio.wait_for(graph.ainvoke(None, config, context=context), timeout=max(0.01, 180 - (time.monotonic() - context.started))) if state.next else state.values
        else:
            history = await conversation_history(context, job, content) if job.kind == 'message' else []
            inputs = {'messages': [*history, HumanMessage(id=f'job:{job.id}', content=content)]}
            result = await asyncio.wait_for(graph.ainvoke(inputs, config, context=context), timeout=max(0.01, 180 - (time.monotonic() - context.started)))
    messages = result.get('messages', [])
    answer = next((m for m in reversed(messages) if isinstance(m, AIMessage) and not m.tool_calls), None)
    if answer is None:
        raise ValueError('模型未返回可用答复')
    async with context.sessions() as db:
        await lease(db, context)
    # These messages come from this job's guarded graph, never model-supplied
    # citations or prior conversation prose. Re-authorization occurs at review.
    context.reply_evidence = [
        {'id': index, 'tool': message.name, 'result': message.content}
        for index, message in enumerate(messages)
        if isinstance(message, ToolMessage) and message.name in ALLOWED_TOOLS | TEAM_TOOL_NAMES
    ]
    return answer.text[:16000]
