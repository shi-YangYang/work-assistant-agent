"""Controlled fault injection. Uses only the dedicated PostgreSQL test fixture."""
import asyncio
import json
import time
from datetime import timedelta
from types import SimpleNamespace
import httpx
import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from sqlalchemy import func, select
from app.agent.intent import authorize_intent
from app.agent.model import BoundedChatModel
from app.agent.operations import execute
from app.agent.tool_nodes import outcome, tool_node
from app.db.base import now
from app.integrations.models.transport import ProviderError, status_error
from app.modules.members.models import Member
from app.modules.messages.models import Message
from app.modules.model_services.models import ModelUsage
from app.modules.operations.models import BusinessAction
from app.modules.work.models import WorkItem
from app.tasks import node_execution
from app.tasks.context import InputChanged, LostLease, RunContext
from app.tasks.models import Job
from app.tasks.node_failures import classify
from app.tasks.node_state import execution, node_dtos, save
from app.tasks.queue import claim
from app.tasks.retry import Attempt, Failure, NodeFailed, run
from test_business_actions import create, read_work, runtime

pytestmark = pytest.mark.asyncio


async def noop(*args):
    pass


@pytest.mark.parametrize('failures', [0, 2, 4])
async def test_core_attempt_limit_and_backoff(failures):
    clock = [100.0]
    calls, events, delays = [], [], []
    async def operation():
        calls.append(True)
        if len(calls) <= failures:
            raise TimeoutError()
        return 'result'
    async def wait(delay):
        delays.append(delay)
        clock[0] += delay
    async def emit(state, attempt, failure):
        events.append((state, attempt.count, attempt.next_at))
    request = run(operation, classify=lambda e: Failure('timeout', 'waiting', True), before=noop,
                  emit=emit, wait=wait, clock=lambda: clock[0])
    if failures == 4:
        with pytest.raises(NodeFailed):
            await request
    else:
        assert await request == 'result'
    assert len(calls) == min(failures + 1, 4)
    assert [count for state, count, _ in events if state == 'running'] == list(range(1, len(calls) + 1))
    assert sum(delays) == (0 if failures == 0 else 3 if failures == 2 else 7)


async def test_core_retry_after_deadline_and_cancel():
    clock = [0.0]
    async def failure():
        raise TimeoutError()
    async def wait(delay):
        clock[0] += delay
    with pytest.raises(NodeFailed) as error:
        await run(failure, classify=lambda e: Failure('throttle', 'wait', True, 12),
                  before=noop, emit=noop, clock=lambda: clock[0], wait=wait, deadline=10)
    assert error.value.failure.code == 'deadline' and clock == [0]
    async def cancel():
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await run(cancel, classify=classify, before=noop, emit=noop)
    attempt = Attempt(3)
    with pytest.raises(NodeFailed):
        await run(failure, classify=classify, before=noop, emit=noop, attempt=attempt)
    assert attempt.count == 4


async def test_failure_classification_is_structured_and_conservative():
    for code in ('authentication', 'quota', 'protocol', 'address', 'revoked'):
        assert not classify(ProviderError(code, 'controlled')).retryable
    assert not classify(ValueError('timeout network 503')).retryable
    assert not classify(RuntimeError('temporary')).retryable
    assert not classify(NodeFailed(Failure('timeout', 'child exhausted', True))).retryable
    assert classify(InputChanged()).cancelled
    assert not classify(HTTPException(403, detail={'code': 'business_access_changed'})).retryable
    for reason, expected in [('rate_limit_exceeded', True), ('insufficient_quota', False), ('unknown', False)]:
        with pytest.raises(ProviderError) as result:
            status_error(httpx.Response(429, json={'error': {'code': reason}}, headers={'Retry-After': '3'}))
        assert classify(result.value).retryable is expected
        assert result.value.retry_after == 3


@pytest.fixture
def fast_nodes(monkeypatch):
    real = node_execution.run
    async def fast(*args, **kwargs):
        clock = [time.time()]
        async def wait(delay):
            clock[0] += delay
        return await real(*args, **{**kwargs, 'jitter': lambda: 0}, clock=lambda: clock[0], wait=wait)
    monkeypatch.setattr(node_execution, 'run', fast)


async def enabled(setup):
    context, sent = await runtime(setup)
    context.node_retry = True
    await node_execution.initialize(context, 'fixed-input')
    return context, sent


async def test_nested_exhaustion_and_manual_retry_preserve_history(setup, fast_nodes):
    context, _ = await enabled(setup)
    calls = []
    class BrokenJudge:
        async def ainvoke(self, prompt):
            calls.append(True)
            raise ProviderError('timeout', '模型暂未响应')
    context.intent_model = BrokenJudge()
    async def write():
        return await execute(context, step=1, action='create_work', changes={'title': '报价方案'})
    with pytest.raises(NodeFailed):
        await node_execution.execute_node(context, identity='tool', kind='tool', label='创建工作', operation=write)
    assert len(calls) == 4
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        rows = node_dtos(job)
        assert [row['attempts'] for row in rows] == [1, 4]
        assert rows[1]['parentId'] == rows[0]['id']
        assert await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == context.owner_id)) == 0
        job.state, job.lease_until = 'awaiting_retry', None
    response = await setup[3]['employee'].post(f'/api/v1/jobs/{context.job_id}/retry', json={})
    assert response.status_code == 200
    resumed = await claim(context.sessions, context.owner_id)
    context.fence = resumed.fence
    await node_execution.initialize(context, 'fixed-input')
    from test_business_actions import Judge
    context.intent_model = Judge()
    result = await node_execution.execute_node(context, identity='tool', kind='tool', label='创建工作', operation=write)
    assert result['state'] == 'succeeded'
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        child = execution(job)['nodes'][1]
        assert child['attempts'] == 1 and child['totalRetries'] == 3 and child['history'][0]['attempts'] == 4


@pytest.mark.parametrize('commit_attempt', [1, 4])
async def test_committed_write_receipt_survives_delivery_failure(setup, fast_nodes, commit_attempt):
    context, _ = await enabled(setup)
    calls = []
    attempts = []
    async def write():
        attempts.append(True)
        if len(attempts) < commit_attempt:
            raise ProviderError('network', 'controlled pre-write failure')
        result = await execute(context, step=1, action='create_work', changes={'title': '报价方案'})
        calls.append(result['id'])
        if len(calls) == 1:
            raise ProviderError('network', 'connection lost after commit')
        return result
    result = await node_execution.execute_node(context, identity='save', kind='tool', label='创建工作', operation=write)
    assert result['state'] == 'succeeded' and len(calls) == 1
    assert len(attempts) == commit_attempt
    assert len(context.intent_model.inputs) == 1
    assert await node_execution.execute_node(context, identity='save', kind='tool', label='创建工作', operation=write) == result
    assert len(calls) == 1
    async with context.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(BusinessAction).where(BusinessAction.owner_id == context.owner_id)) == 1
        assert execution(await db.get(Job, context.job_id))['nodes'][0]['attempts'] == commit_attempt


async def test_worker_recovery_keeps_spent_attempt_and_completed_result(setup, fast_nodes):
    context, _ = await enabled(setup)
    async def result():
        return 'completed'
    await node_execution.execute_node(context, identity='first', kind='tool', label='查询', operation=result)
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        state = execution(job)
        row = dict(state['nodes'][0], id='interrupted', state='running', attempts=3)
        row.pop('output')
        state['nodes'].append(row)
        save(job, state)
        job.lease_until = now() - timedelta(seconds=1)
    recovered = await claim(context.sessions, context.owner_id)
    assert recovered and recovered.attempt == 0 and recovered.fence > context.fence
    context.fence = recovered.fence
    await node_execution.initialize(context, 'fixed-input')
    async def forbidden():
        raise AssertionError('successful node repeated')
    assert await node_execution.execute_node(context, identity='first', kind='tool', label='查询', operation=forbidden) == 'completed'
    # Recover the actual stable id to reproduce the pre-IO persisted boundary.
    from app.core.digests import digest
    target = digest({'scope': context.node_scope, 'parent': None, 'kind': 'tool', 'identity': 'second'})
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        state = execution(job)
        state['nodes'][1]['id'] = target
        save(job, state)
    calls = []
    async def broken():
        calls.append(True)
        raise ProviderError('timeout', 'timeout')
    with pytest.raises(NodeFailed):
        await node_execution.execute_node(context, identity='second', kind='tool', label='查询', operation=broken)
    assert len(calls) == 1


@pytest.mark.parametrize('change', ['permission', 'input', 'cancel'])
async def test_wait_revalidates_permission_input_and_cancellation(setup, fast_nodes, change):
    context, _ = await enabled(setup)
    calls = []
    async def break_then_change():
        calls.append(True)
        async with context.sessions.begin() as db:
            job = await db.get(Job, context.job_id)
            if change == 'permission':
                member = await db.get(Member, context.owner_id)
                member.active = False
            elif change == 'input':
                message = await db.get(Message, job.target_id)
                message.transcript_revision += 1
            else:
                job.state = 'cancelled'
        raise ProviderError('timeout', 'controlled')
    with pytest.raises((LostLease, InputChanged)):
        await node_execution.execute_node(context, identity='change', kind='model', label='思考中', operation=break_then_change)
    assert len(calls) == 1


async def test_cached_read_is_rejected_after_business_revision_changes(setup, fast_nodes):
    context, _ = await enabled(setup)
    work = await create(setup[3]['employee'])
    async def read():
        return await read_work(context, work['id'])
    await node_execution.execute_node(context, identity='read', kind='tool', label='读取工作', operation=read)
    async with context.sessions.begin() as db:
        item = await db.get(WorkItem, work['id'])
        item.revision += 1
    with pytest.raises(ProviderError, match='已变化'):
        await node_execution.execute_node(context, identity='read', kind='tool', label='读取工作', operation=read)


async def test_real_model_adapter_records_each_actual_attempt_and_isolates_other_jobs(setup, fast_nodes, monkeypatch):
    context, _ = await enabled(setup)
    context.model_binding = {'assistant': {'model': 'controlled'}}
    async def resolve(*args):
        return {'model': 'controlled'}, 'controlled-test-key'
    monkeypatch.setattr('app.modules.model_services.bindings.resolve_bound', resolve)
    calls = []
    async def chat(*args, on_event, **kwargs):
        calls.append(True)
        await on_event('started')
        if len(calls) < 3:
            raise ProviderError('timeout', '模型暂未响应')
        await on_event('usage', {'prompt_tokens': 7, 'completion_tokens': 2})
        return {'choices': [{'message': {'role': 'assistant', 'content': '结果'}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 7, 'completion_tokens': 2}}
    monkeypatch.setattr('app.integrations.models.chat.chat', chat)
    model = BoundedChatModel(model='controlled', api_key='unused', max_retries=0)
    model._run_context = context
    prompt = [HumanMessage(id='logical-1', content='查询')]
    assert (await model.ainvoke(prompt)).content == '结果'
    assert (await model.ainvoke(prompt)).content == '结果' and len(calls) == 3
    assert (await model.ainvoke([HumanMessage(id='logical-2', content='查询')])).content == '结果'
    assert len(calls) == 4
    async with context.sessions() as db:
        rows = (await db.scalars(select(ModelUsage).where(ModelUsage.job_id == context.job_id).order_by(ModelUsage.created_at))).all()
        assert [r.status for r in rows] == ['unknown', 'unknown', 'succeeded', 'succeeded']
        assert rows[0].actual_input_tokens is None and rows[2].actual_input_tokens == 7
    context.node_retry = False
    calls.clear()
    with pytest.raises(ProviderError):
        await model.ainvoke(prompt)
    assert len(calls) == 1


async def test_parallel_identical_tools_have_distinct_nodes_and_structured_refusal(setup, fast_nodes):
    context, _ = await enabled(setup)
    async def one(identifier):
        request = SimpleNamespace(tool_call={'name': 'find_work_items', 'id': identifier, 'args': {'query': ''}}, state={'messages': [AIMessage(id='batch', content='', tool_calls=[{'name': 'find_work_items', 'id': identifier, 'args': {'query': ''}}])]})
        async def operation():
            return ToolMessage(content=json.dumps({'state': 'conflict', 'message': 'controlled'}), tool_call_id=identifier)
        return await tool_node(context, request, operation)
    await asyncio.gather(one('one'), one('two'))
    async with context.sessions() as db:
        rows = node_dtos(await db.get(Job, context.job_id))
        assert len(rows) == 2 and all(row['state'] == 'failed' and not row['canRetry'] for row in rows)
    assert outcome(ToolMessage(content='{"state":"pending"}', tool_call_id='x'))[0] == 'awaiting_confirmation'
    assert outcome(ToolMessage(content='{"state":"running","job":{}}', tool_call_id='x'))[0] == 'succeeded'


async def test_harness_manual_resume_only_retries_failed_model_after_committed_tool(setup, fast_nodes, monkeypatch):
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from app.tasks.handlers import process_job
    from test_model_services import create as service_create, route
    from test_company import send
    settings, sessions, users, clients = setup
    service = await service_create(clients['admin'])
    assert (await clients['admin'].put('/api/v1/settings/model-routing', json=route(service))).status_code == 200
    counts = {'initial': 0, 'intent': 0, 'final': 0, 'review': 0}
    recovery = [False]
    async def chat(settings, config, key, messages, *, on_event, tools=None, **kwargs):
        await on_event('started')
        if not tools:
            payload = json.loads(messages[-1]['content'])
            if payload.get('task') == 'business_reply_review':
                counts['review'] += 1
                content = json.dumps({'segments': [{'index': p['index'], 'kind': 'information', 'evidence': []} for p in payload['segments']]})
            else:
                counts['intent'] += 1
                content = json.dumps({'allowed': True, 'quote': payload['currentUserText'], 'reason': '', 'receiptOnly': False})
            message, finish = {'role': 'assistant', 'content': content}, 'stop'
        elif messages[-1]['role'] == 'tool':
            counts['final'] += 1
            if not recovery[0]:
                raise ProviderError('timeout', '模型暂未响应')
            message, finish = {'role': 'assistant', 'content': '可继续补充工作信息。'}, 'stop'
        else:
            counts['initial'] += 1
            message, finish = {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'create-1', 'type': 'function', 'function': {'name': 'execute_business_action', 'arguments': json.dumps({'step': 1, 'action': 'create_work', 'changes': {'title': '报价方案'}})}}]}, 'tool_calls'
        await on_event('usage', {'prompt_tokens': 12, 'completion_tokens': 5})
        return {'choices': [{'message': message, 'finish_reason': finish}], 'usage': {'prompt_tokens': 12, 'completion_tokens': 5}}
    monkeypatch.setattr('app.integrations.models.chat.chat', chat)
    sent = await send(clients['employee'], '帮我创建工作：报价方案，并告诉我还能做什么')
    job = await claim(sessions, users['employee'].id)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(job, sessions, settings, saver)
        detail = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
        assert detail['job']['state'] == 'awaiting_retry', detail['job']
        assert counts == {'initial': 1, 'intent': 1, 'final': 4, 'review': 0}
        assert len(detail['actions']) == 1 and detail['actions'][0]['state'] == 'succeeded'
        failed_id = next(row['id'] for row in detail['job']['nodes'] if row['state'] == 'failed')
        recovery[0] = True
        assert (await clients['employee'].post(f'/api/v1/jobs/{job.id}/retry', json={})).status_code == 200
        resumed = await claim(sessions, users['employee'].id)
        await process_job(resumed, sessions, settings, saver)
    detail = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert detail['job']['state'] == 'succeeded', detail['job']
    assert counts == {'initial': 1, 'intent': 1, 'final': 5, 'review': 1}
    assert len(detail['actions']) == 1
    recovered_node = next(row for row in detail['job']['nodes'] if row['id'] == failed_id)
    assert recovered_node['state'] == 'succeeded' and recovered_node['attempts'] == 1 and recovered_node['totalRetries'] == 3


async def test_report_enqueue_receipt_is_not_repeated_or_report_completion(setup, fast_nodes):
    await create(setup[3]['employee'])
    context, _ = await enabled(setup)
    calls = []
    request = SimpleNamespace(tool_call={'name': 'execute_business_action', 'id': 'enqueue', 'args': {'action': 'generate_report'}}, state={'messages': [AIMessage(id='enqueue-model', content='', tool_calls=[{'name': 'execute_business_action', 'id': 'enqueue', 'args': {}}])]})
    async def operation():
        result = await execute(context, step=1, action='generate_report', report_date=now().date().isoformat())
        calls.append(result)
        if len(calls) == 1:
            raise ProviderError('network', 'response lost')
        return ToolMessage(content=json.dumps(result), name='execute_business_action', tool_call_id='enqueue')
    result = await tool_node(context, request, operation)
    assert json.loads(result.content)['state'] == 'running'
    assert len(calls) == 1 and calls[0]['job']['id'] == json.loads(result.content)['job']['id']
    async with context.sessions() as db:
        report_jobs = (await db.scalars(select(Job).where(Job.owner_id == context.owner_id, Job.kind == 'report'))).all()
        assert len(report_jobs) == 1 and not report_jobs[0].result.get('nodeExecution')
        nodes = node_dtos(await db.get(Job, context.job_id))
        assert nodes[0]['label'] == '报告生成入队' and nodes[0]['state'] == 'succeeded'


async def test_serialization_conflict_rolls_back_before_new_transaction(setup, fast_nodes):
    from sqlalchemy.exc import DBAPIError
    from psycopg.errors import SerializationFailure
    context, _ = await enabled(setup)
    work = await create(setup[3]['employee'])
    calls = []
    async def change():
        async with context.sessions.begin() as db:
            row = await db.get(WorkItem, work['id'])
            calls.append(row.revision)
            row.revision += 1
            await db.flush()
            if len(calls) == 1:
                raise DBAPIError('controlled', {}, SerializationFailure())
            return row.revision
    assert await node_execution.execute_node(context, identity='transaction', kind='tool', label='保存', operation=change) == 2
    assert calls == [1, 1]


async def test_unsent_connection_failures_are_not_reported_as_actual_calls(setup, fast_nodes, monkeypatch):
    context, _ = await enabled(setup)
    async def resolve(*args):
        return {'model': 'controlled'}, 'test'
    monkeypatch.setattr('app.modules.model_services.bindings.resolve_bound', resolve)
    async def chat(*args, on_event, **kwargs):
        await on_event('started')
        raise httpx.ConnectError('controlled-connect-failure')
    monkeypatch.setattr('app.integrations.models.chat.chat', chat)
    model = BoundedChatModel(model='controlled', api_key='unused', max_retries=0)
    model._run_context = context
    with pytest.raises(NodeFailed):
        await model.ainvoke([HumanMessage(content='request')])
    async with context.sessions() as db:
        rows = (await db.scalars(select(ModelUsage).where(ModelUsage.job_id == context.job_id))).all()
        assert len(rows) == 4 and all(row.status == 'not_sent' and row.started_at is None for row in rows)


async def test_malformed_authorization_retries_without_inventing_successful_usage(setup, fast_nodes, monkeypatch):
    context, _ = await enabled(setup)
    context.intent_model = None
    async def resolve(*args):
        return {'model': 'controlled', 'parameters': {}, 'baseUrl': 'https://example.com'}, 'test'
    monkeypatch.setattr('app.modules.model_services.bindings.resolve_bound', resolve)
    calls = []
    async def chat(*args, on_event, **kwargs):
        calls.append(True)
        await on_event('started')
        await on_event('usage', {'prompt_tokens': 5, 'completion_tokens': 2})
        return {'choices': [{'message': {'role': 'assistant', 'content': '{malformed'}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 5, 'completion_tokens': 2}}
    monkeypatch.setattr('app.integrations.models.chat.chat', chat)
    with pytest.raises(NodeFailed):
        await execute(context, step=1, action='create_work', changes={'title': '报价方案'})
    assert len(calls) == 4
    async with context.sessions() as db:
        rows = (await db.scalars(select(ModelUsage).where(ModelUsage.job_id == context.job_id))).all()
        assert len(rows) == 4 and all(row.status == 'failed' and row.actual_input_tokens == 5 for row in rows)
        assert await db.scalar(select(func.count()).select_from(BusinessAction).where(BusinessAction.owner_id == context.owner_id)) == 0


async def test_business_revision_change_stops_a_model_before_its_next_attempt(setup, fast_nodes):
    context, _ = await enabled(setup)
    work = await create(setup[3]['employee'])
    await read_work(context, work['id'])
    calls = []
    async def request():
        calls.append(True)
        async with context.sessions.begin() as db:
            item = await db.get(WorkItem, work['id'])
            item.revision += 1
        raise ProviderError('timeout', 'controlled')
    with pytest.raises(ProviderError, match='已变化'):
        await node_execution.execute_node(context, identity='model', kind='model', label='思考中', operation=request)
    assert len(calls) == 1
