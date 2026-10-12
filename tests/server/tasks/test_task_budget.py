"""Internal budget arithmetic and real PostgreSQL reservation/recovery boundaries."""
import asyncio
import json
from types import SimpleNamespace
import pytest
from app.tasks.budget import TaskBudgetStopped
from app.tasks.budget.state import create, snapshot, reserve, policy
from app.tasks.budget import service
from app.tasks.context import RunContext
from app.tasks.lease import lease
from app.tasks.models import Job
from app.tasks.nodes.node_execution import initialize, execute_node
from app.tasks.nodes.node_state import reopen_failed
from app.agent.runtime.model import reserve_call
from _support.agent.business_actions import runtime


def test_policy_thresholds_and_final_answer_reserve():
    state = create(2, 100)
    assert state['deadlineAt'] == 1900 and policy(state).tools == 64
    for index in range(64):
        state = reserve(state, 'tool', 110, identity=str(index))
    assert snapshot(state, 110)['phase'] == 'finalizing'
    with pytest.raises(TaskBudgetStopped):
        reserve(state, 'tool', 110, identity='excess')
    # The last admitted tool may still authorize/convert, but not use the
    # reserved final-answer model requests or the reserved time.
    state = reserve(state, 'model', 110, admitted_tool=True)
    state['models'] = 93
    with pytest.raises(TaskBudgetStopped):
        reserve(state, 'model', 110, admitted_tool=True)
    for _ in range(3):
        state = reserve(state, 'model', 110, final_answer=True)
    with pytest.raises(TaskBudgetStopped):
        reserve(state, 'model', 110, final_answer=True)
    state = create(0, 100)
    assert snapshot(state, 1719)['phase'] == 'working'
    assert snapshot(state, 1720)['phase'] == 'near_limit'
    assert snapshot(state, 1780)['phase'] == 'finalizing'
    assert snapshot(state, 1900)['phase'] == 'exhausted'
    assert snapshot(state, 521)['phase'] == 'working'
    with pytest.raises(TaskBudgetStopped):
        reserve(state, 'model', 1900, final_answer=True)


def test_legacy_policy_preserves_count_deadline_and_freezes_configuration():
    context = SimpleNamespace()
    job = SimpleNamespace(kind='message', attempt=3, result={'nodeExecution': {
        'deadline': 520, 'scope': 'old', 'actualCalls': 12,
        'nodes': [{'kind': 'tool', 'id': str(i), 'scope': 'old'} for i in range(7)],
    }})
    state = service.ensure(job, context, instant=400)
    assert policy(state).version == 'assistant-legacy'
    assert state['models'] == 12 and state['tools'] == 7 and state['deadlineAt'] == 520
    assert state['startedAt'] == 100 and state['round'] == 3
    assert service.ensure(job, context, instant=500) == state
    service.finish(job, instant=505)
    assert job.result['taskBudget']['endedAt'] == 505
    assert snapshot(job.result['taskBudget'], 900)['phase'] == 'ended'


@pytest.mark.asyncio
async def test_parallel_reservations_do_not_overdraw_or_emit_budget_events(setup):
    context, _ = await runtime(setup)
    context.node_retry = True
    await initialize(context, 'parallel')
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        state = {**job.result['taskBudget'], 'tools': 62}
        job.result = {**job.result, 'taskBudget': state}
        sequence = job.feedback['seq']
    async def consume(index):
        try:
            async with context.sessions.begin() as db:
                job, _ = await lease(db, context)
                service.consume(job, context, 'tool', identity=str(index))
            return True
        except TaskBudgetStopped:
            return False
    assert sum(await asyncio.gather(*(consume(i) for i in range(5)))) == 2
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        assert job.result['taskBudget']['tools'] == 64
        assert job.feedback['seq'] == sequence
        job.result = {**job.result, 'taskBudget': {**job.result['taskBudget'], 'tools': 0, 'models': 94}}
    async def model():
        try:
            await reserve_call(context, 'assistant', final_answer=True)
            return True
        except TaskBudgetStopped:
            return False
    assert sum(await asyncio.gather(*(model() for _ in range(5)))) == 2
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert job.result['taskBudget']['models'] == 96


@pytest.mark.asyncio
async def test_tool_retries_scope_worker_recovery_and_explicit_retry(setup, monkeypatch):
    from app.integrations.models.transport import ProviderError
    context, _ = await runtime(setup)
    context.node_retry = True
    await initialize(context, 'first')
    attempts = []
    async def operation():
        attempts.append(1)
        if len(attempts) == 1:
            raise ProviderError('timeout', 'controlled')
        return {'result': 'ok'}
    assert await execute_node(context, identity='same', kind='tool', label='查找工作', operation=operation) == {'result': 'ok'}
    assert len(attempts) == 2 and context.tools == 1
    assert await execute_node(context, identity='same', kind='tool', label='查找工作', operation=operation) == {'result': 'ok'}
    assert len(attempts) == 2 and context.tools == 1
    await reserve_call(context, 'assistant')
    await reserve_call(context, 'asr')
    deadline = context.node_deadline
    recovered = RunContext(context.owner_id, context.company_id, context.job_id, context.fence, context.sessions, context.settings, node_retry=True)
    await initialize(recovered, 'changed-scope')
    assert recovered.tools == 1 and recovered.calls == 2 and recovered.node_deadline == deadline
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        reopen_failed(job)
        job.attempt += 1
        service.ensure(job, recovered)
        assert recovered.tools == recovered.calls == 0
        assert policy(recovered.task_budget).version == 'assistant-v1'
        assert recovered.node_deadline > deadline


@pytest.mark.asyncio
async def test_last_admitted_tool_auxiliary_model_and_reserved_pool(setup):
    context, _ = await runtime(setup)
    context.node_retry = True
    await initialize(context, 'last-tool')
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        job.result = {**job.result, 'taskBudget': {**job.result['taskBudget'], 'tools': 63}}
    async def operation():
        await reserve_call(context, 'assistant')
        return 'saved'
    assert await execute_node(context, identity='last', kind='tool', label='保存工作', operation=operation) == 'saved'
    assert context.tools == 64 and context.calls == 1
    with pytest.raises(TaskBudgetStopped):
        await reserve_call(context, 'asr')


@pytest.mark.asyncio
async def test_main_prompt_is_ephemeral_and_auxiliary_calls_cannot_spend_reserve(setup, monkeypatch):
    from langchain_core.messages import HumanMessage
    from app.agent.runtime.model import BoundedChatModel, internal_call_kind
    from app.agent.runtime.budget import final_answer_call
    from app.agent.completion.delivery import validate_completion_response
    context, _ = await runtime(setup)
    context.node_retry = True
    await initialize(context, 'prompt')
    requests = []
    async def resolve(*args):
        return {'model': 'controlled', 'parameters': {}}, 'controlled'
    async def chat(settings, config, key, messages, **kwargs):
        requests.append(messages)
        return {'choices': [{'message': {'role': 'assistant', 'content': '<!--noria:{}-->\n这是回答。'}, 'finish_reason': 'stop'}]}
    monkeypatch.setattr('app.modules.model_services.bindings.resolve_bound', resolve)
    monkeypatch.setattr('app.integrations.models.chat.chat', chat)
    model = BoundedChatModel(model='controlled', api_key='unused', max_retries=0)
    model._run_context, model._completion_validator = context, validate_completion_response
    messages = [HumanMessage(content='问候', id='prompt-user')]
    await model.ainvoke(messages)
    assert len(messages) == 1
    assert '还可调用工具 64 次' in requests[0][-1]['content']
    assert '探索模型请求 92 次' in requests[0][-1]['content']
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        assert '内部执行信息' not in json.dumps(job.result, ensure_ascii=False)
        job.result = {**job.result, 'taskBudget': {**job.result['taskBudget'], 'models': 93}}
    outer = final_answer_call.set(True)
    internal = internal_call_kind.set('context_compaction')
    try:
        with pytest.raises(Exception) as caught:
            await model.ainvoke([HumanMessage(content='内部压缩', id='different')])
        from app.agent.completion.recovery.budget import stopped
        assert stopped(caught.value)
    finally:
        internal_call_kind.reset(internal)
        final_answer_call.reset(outer)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('initial, expected_calls', [(94, 2), (95, 1)])
async def test_provider_compatibility_requests_each_reserve_and_cannot_overdraw(setup, monkeypatch, initial, expected_calls):
    from sqlalchemy import select
    from langchain_core.messages import HumanMessage
    from app.agent.runtime.model import BoundedChatModel
    from app.agent.runtime.budget import final_answer_call
    from app.agent.completion.delivery import validate_completion_response
    from app.integrations.models.transport import ProviderError
    from app.modules.model_services.models import ModelUsage
    context, _ = await runtime(setup)
    context.node_retry = True
    await initialize(context, 'compatibility')
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        job.result = {**job.result, 'taskBudget': {**job.result['taskBudget'], 'models': initial}}
    async def resolve(*args):
        return {'model': 'controlled', 'parameters': {}, 'streaming': False}, 'controlled'
    calls = []
    async def wire(settings, config, key, messages, *, tool_choice, on_event, **kwargs):
        calls.append(tool_choice)
        await on_event('started')
        if tool_choice == 'required':
            raise ProviderError('tool_choice_unsupported', 'controlled explicit rejection')
        return {'choices': [{'message': {'role': 'assistant', 'content': '<!--noria:{}-->\n完整回答。'}, 'finish_reason': 'stop'}]}
    monkeypatch.setattr('app.modules.model_services.bindings.resolve_bound', resolve)
    monkeypatch.setattr('app.integrations.models.chat._chat', wire)
    model = BoundedChatModel(model='controlled', api_key='unused', max_retries=0)
    model._run_context, model._completion_validator = context, validate_completion_response
    token = final_answer_call.set(True)
    from app.tasks.nodes.node_execution import active_node
    node_token = active_node.set(('compatibility-test', 'model'))
    try:
        operation = model._single([HumanMessage(content='整理答案')], tool_choice='required')
        if initial == 95:
            with pytest.raises(TaskBudgetStopped):
                await operation
        else:
            assert (await operation).generations[0].message.content.endswith('完整回答。')
    finally:
        active_node.reset(node_token)
        final_answer_call.reset(token)
    assert len(calls) == expected_calls
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        usages = (await db.scalars(select(ModelUsage).where(ModelUsage.job_id == job.id))).all()
        assert job.result['taskBudget']['models'] == 96
        assert len(usages) == expected_calls
        assert sorted(row.status for row in usages) == (['failed', 'succeeded'] if expected_calls == 2 else ['failed'])
