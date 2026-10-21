from app.agent.memory.middleware import prepare as prepare_memory, validate_completed as validate_memory_completed
from app.modules.executions.builtin.schemas import EXECUTION_TOOLS
import asyncio
import hashlib
import json
import time
from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.profiles import GeneralPurposeSubagentProfile, HarnessProfile, register_harness_profile
from app.agent.context.compaction import ContextCompaction
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langsmith import tracing_context
from app.agent.context.history import conversation_history
from app.agent.completion.delivery import PUBLIC_REPLY_POLICY, from_messages, take_repair, validate_completion_response
from app.agent.runtime.middleware import ToolBoundary, repairing_delivery
from app.agent.runtime.budget import invoke as invoke_bounded
from app.agent.runtime.model import BoundedChatModel, approximate_tokens
from app.agent.prompts.persona import runtime_persona_prompt
from app.agent.prompts.main import main_policy
from app.agent.prompts.policies import ALLOWED_TOOLS, EXCLUDED_TOOLS, TEAM_TOOL_NAMES
from app.agent.tools.registry import BUSINESS_TOOLS
from app.agent.tools.business.team import TEAM_TOOLS
from app.core.personas import LEGACY_PERSONA
from app.db.base import now
from app.modules.messages.models import Message
from app.security.access import scope as business_scope
from app.tasks.context import RunContext
from app.tasks.lease import lease


register_harness_profile('openai', HarnessProfile(excluded_tools=EXCLUDED_TOOLS, excluded_middleware=frozenset({'SummarizationMiddleware'}), general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)))


def build_graph(settings, checkpointer, context, model=None):
    if model is None:
        choice = (context.model_binding or {}).get(context.model_purpose) or {}
        model = BoundedChatModel(model=choice.get('model', 'unconfigured'), api_key='server-managed', max_retries=0, timeout=60, max_tokens=None, streaming=False, use_responses_api=False, stream_usage=False)
        model._run_context = context
    if isinstance(model, BoundedChatModel):
        model._completion_validator = validate_completion_response
    from app.agent.prompts.execution_mode import mode_prompt
    graph = create_deep_agent(model, tools=[tool for tool in BUSINESS_TOOLS if tool.name not in EXECUTION_TOOLS or (getattr(context.settings, 'sandbox_url', '') and getattr(context.settings, 'sandbox_token', ''))] + (TEAM_TOOLS if context.role == 'admin' else []), system_prompt=main_policy(context.role) + '\n' + runtime_persona_prompt(context.persona_id) + '\n' + mode_prompt(getattr(context, 'execution_mode', 'auto')) + '\n' + getattr(context, 'request_clock', ''), middleware=[ToolBoundary(), ContextCompaction(model)], subagents=[], backend=StateBackend(), context_schema=RunContext, checkpointer=checkpointer)
    return graph


async def invoke_harness(context, checkpointer, content, model=None, *, repair_missing_action=False):
    from app.agent.context.checkpoints import GuardedSaver
    async with context.sessions.begin() as db:
        live, actor = await lease(db, context)
        if not live.access:
            live.access = business_scope(actor)
        context.role = actor.role
        from app.modules.operations.policy.execution_policy import mode_for
        context.execution_mode = await mode_for(db, live)
        from app.modules.model_services.bindings import freeze_capacities
        if context.model_binding:
            await freeze_capacities(db, context.model_binding)
    from app.modules.members.models import Company
    async with context.sessions() as db:
        company = await db.get(Company, context.company_id)
        message = await db.get(Message, live.target_id) if live.kind == 'message' else None
        clock = message.created_at if message else now()
        from app.agent.context.request_clock import instruction as clock_instruction
        clock_note = clock_instruction(clock, company.rules['timezone'])
    context.request_clock = clock_note
    await prepare_memory(context)
    graph = build_graph(context.settings, GuardedSaver(checkpointer, context), context, model)
    async with context.sessions() as db:
        job, actor = await lease(db, context)
        # Checkpoints include pending executable tools. Never share them between jobs,
        # even for the same employee or report; history below contains business data only.
        thread = f'{actor.company_id}:{actor.id}:job:{job.id}'
        if context.node_retry:
            thread += ':scope:' + context.node_scope
        if context.model_binding is not None:
            config_digest = hashlib.sha256(json.dumps(context.model_binding, sort_keys=True).encode()).hexdigest()
            thread += f':config:{context.config_attempt}:{config_digest}'
        if job.kind == 'message':
            if context.source_revision is None:
                raise ValueError('消息输入版本缺失，无法恢复处理')
            digest = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            if context.persona_id != LEGACY_PERSONA:
                thread += f':persona:{context.persona_id}'
            thread += f':input:{context.source_revision}:{digest}'
            if context.document_snapshot:
                thread += ':files:' + context.document_snapshot
    history = await conversation_history(context, job, content) if job.kind == 'message' else []
    if context.work_reference_snapshot:
        reference_digest = hashlib.sha256(json.dumps(context.work_reference_snapshot, sort_keys=True).encode()).hexdigest()
        thread += ':work:' + reference_digest
    context.compaction_packet, context.compaction_loaded = None, False
    context.context_checkpoint = GuardedSaver(checkpointer, context)
    context.context_checkpoint_config = {'configurable': {'thread_id': thread + ':context', 'checkpoint_ns': ''}}
    from app.tasks.budget.state import policy
    config = {'configurable': {'thread_id': thread}, 'recursion_limit': policy(context.task_budget).graph_steps if context.task_budget else 36, 'callbacks': []}
    with tracing_context(enabled=False):
        state = await graph.aget_state(config)
        # Completed graphs bypass middleware. Recover compacted evidence as well
        # as the final prose before independent review, including a fresh worker.
        from app.agent.context.compaction import saved_packet, publish_packet
        packet = await saved_packet(context)
        if packet:
            await publish_packet(context, packet)
            context.context_evidence = packet.get('evidence', [])
        repair_id = f'completion-repair:{job.id}'
        repaired = any(m.id == repair_id for m in state.values.get('messages', []))
        if state.values and repair_missing_action and not repaired and not state.next:
            instruction = '内部纠错（不是用户新请求）：收尾标记与实际操作可能不一致。先 get_business_actions 读取当前回执，逐项对照用户原请求，判断是否真的遗漏操作。若原请求仅查询、整理、生成私人成果，或明确不要保存业务记录，则无业务回执是正常的；保留正确正文，不添加业务写入。确有遗漏时，仅补尚未执行且已获授权的独立步骤。已有 succeeded/pending/running 步骤不重做，不换 step 重复创建；保留原步骤编号，新增步骤避开已用编号。失败或冲突的步骤不盲目重试；依赖项未成功时不继续。用户委托挑选单条删除对象时只准备确认卡，不能直接删除或提交。管理员只写本人工作；跟进员工业务时关联已有真实 source_tokens，独立个人事项不要求员工来源。不得扩展范围，有歧义或剩余任务无法完成时明确说明。最终正文仍只交付用户原请求的结果，不汇报本次内部纠错。'
            result = await invoke_bounded(context, graph.ainvoke({'messages': [HumanMessage(id=repair_id, content=instruction)]}, config, context=context), timeout=max(0.01, context.node_deadline - time.time() if context.node_retry else 180 - (time.monotonic() - context.started)))
        elif state.values:
            # The worker already checked retry authorization and lease. Resume this
            # job's unchanged input; a completed graph needs no second external request.
            result = await invoke_bounded(context, graph.ainvoke(None, config, context=context), timeout=max(0.01, context.node_deadline - time.time() if context.node_retry else 180 - (time.monotonic() - context.started))) if state.next else state.values
        else:
            inputs = {'messages': [*history, HumanMessage(id=f'job:{job.id}', content=content)]}
            result = await invoke_bounded(context, graph.ainvoke(inputs, config, context=context), timeout=max(0.01, context.node_deadline - time.time() if context.node_retry else 180 - (time.monotonic() - context.started)))
    await validate_memory_completed(context)
    messages = result.get('messages', [])
    from app.agent.completion.delivery import delivery_for

    async def read_delivery(items):
        last = next((m for m in reversed(items) if isinstance(m, AIMessage)), None)
        answer = last if last and not last.tool_calls and not last.invalid_tool_calls else None
        delivery = from_messages(items)
        shortcut = answer and (answer.id or '').startswith(('receipt-completion:', 'interaction-wait:'))
        if delivery is None and answer is not None and not shortcut:
            # The checkpoint retains the rejected completion across worker
            # restarts. Preserve only its coherent unfinished state, not an
            # unchecked directive or receipt/authorization declaration.
            pending_task = None
            repair = next((i for i in range(len(items) - 1, -1, -1)
                           if isinstance(items[i], HumanMessage)), None)
            if repair is not None and repairing_delivery(items, job.id):
                previous = next((m for m in reversed(items[:repair]) if isinstance(m, AIMessage)), None)
                if previous and len(previous.tool_calls) == 1 and previous.tool_calls[0]['name'] == 'finish_task':
                    from app.modules.conversations.task.task_schemas import TaskInterpretation
                    try:
                        task = TaskInterpretation.model_validate(previous.tool_calls[0]['args'].get('task', {}))
                        if task.state != 'completed':
                            pending_task = {'state': task.state, 'remaining': task.remaining}
                    except (ValueError, TypeError):
                        pass
            delivery = await delivery_for(context, answer.text, pending_task=pending_task)
        return delivery, answer, shortcut

    delivery, answer, shortcut = await read_delivery(messages)
    if delivery is None and not shortcut and await take_repair(context, 'protocol'):
        # A broken legacy completion gets one prose-only repair. Never require
        # another task form or replay a write to fix answer metadata.
        instruction = '刚才的答复格式或引用无效。依据已有真实结果和工具错误，直接交付修正后的完整正文，不填写内部表单，不再调用工具或重做业务操作；保留真实未完成项。' + PUBLIC_REPLY_POLICY
        with tracing_context(enabled=False):
            result = await invoke_bounded(context, graph.ainvoke({'messages': [HumanMessage(id=f'delivery-repair:{job.id}', content=instruction)]}, config, context=context), timeout=max(.01, context.node_deadline - time.time() if context.node_retry else 180 - (time.monotonic() - context.started)))
        messages = result.get('messages', [])
        delivery, answer, shortcut = await read_delivery(messages)
    context.delivery = delivery.model_dump() if delivery else None
    if delivery is None and answer is None:
        raise ValueError('模型未返回有效收尾，请重试；已保存操作不会重复执行')
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        from app.agent.runtime.decision_flow import finish as finish_decision
        finish_decision(context, job)
    # These messages come from this job's guarded graph, never model-supplied
    # citations or prior conversation prose. Re-authorization occurs at review.
    from app.agent.context.references.work_context import reference_evidence
    from app.agent.completion.evidence.evidence_consistency import tool_evidence
    context.reply_evidence = [*reference_evidence(context), *context.context_evidence, *[
        row for row in tool_evidence(messages, context.job_id) if row['tool'] in ALLOWED_TOOLS | TEAM_TOOL_NAMES
    ]]
    context.reply_evidence = [{**row, 'id': index} for index, row in enumerate(context.reply_evidence)]
    return delivery.answer if delivery else answer.text
