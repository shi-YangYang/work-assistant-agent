"""Real worker/graph paths with deterministic provider IO, no paid API calls."""
import asyncio
import json
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
import pytest
from app.tasks.budget import Policy
from app.tasks.budget import policy as policies
from app.tasks.models import Job
from app.tasks.runtime.queue import claim
from app.tasks.processing.handlers import process_job
from _support.http.company import send
from _support.agent.task_retry import fast_nodes
from _support.agent.agent_budget_flow import provider, response, run

pytestmark = pytest.mark.asyncio


async def test_real_graph_crosses_old_tool_model_and_step_limits(setup, monkeypatch):
    from app.tasks.budget import service
    original = service.create
    monkeypatch.setattr(service, 'create', lambda round_id, instant, **kwargs: original(round_id, instant - 421, **kwargs))
    calls = []
    async def chat(settings, config, key, messages, **kwargs):
        calls.append(messages)
        step = len(calls)
        if step == 1:
            return response(calls=[('discover', 'load_tools', {'groups': ['work']})])
        if step <= 35:
            return response(calls=[(f'find-{step}', 'find_work_items', {'query': f'项目{step}'})])
        return response('<!--noria:{}-->\n查询已完成，没有找到匹配的工作。')
    provider(monkeypatch, chat)
    result, stored = await run(setup)
    assert len(calls) == 36, result
    assert stored['taskBudget']['models'] == 36 and stored['taskBudget']['tools'] == 34
    assert stored['taskBudget']['endedAt'] is not None
    assert result['job']['taskOutcome']['state'] == 'completed'
    assert all('内部执行信息' in call[-1]['content'] for call in calls)
    assert '内部执行信息' not in json.dumps(stored, ensure_ascii=False)
    public = json.dumps(result, ensure_ascii=False)
    assert all(field not in public for field in ('taskBudget', 'toolReservations', 'deadlineAt', 'reserve_models', '工具额度'))


async def test_last_model_failure_stops_without_overdraw_and_sse_hides_budget(setup, monkeypatch, fast_nodes):
    import hashlib
    from app.integrations.models.transport import ProviderError
    from app.tasks.feedback.feedback import events
    monkeypatch.setattr(policies, 'DEFAULT', Policy(models=4, reserve_models=3))
    calls = []
    async def chat(settings, config, key, messages, **kwargs):
        calls.append(kwargs.get('tools'))
        if len(calls) == 1:
            return response(calls=[('discover', 'load_tools', {'groups': ['work']})])
        assert not kwargs.get('tools')
        raise ProviderError('timeout', 'controlled')
    provider(monkeypatch, chat)
    result, stored = await run(setup)
    assert len(calls) == stored['taskBudget']['models'] == 4
    assert result['job']['taskOutcome']['state'] == 'blocked'
    assert result['reply'] and not result['job']['error']
    token = hashlib.sha256(setup[3]['employee'].cookies.get('paa_company_session').encode()).hexdigest()
    stream = events(setup[1], token, result['job']['id'], settings=setup[0], version=2)
    try:
        value = await anext(stream)
        assert value.startswith('event: snapshot')
        assert all(field not in value for field in ('taskBudget', 'toolReservations', 'deadlineAt', 'reserve_models', '内部执行信息'))
    finally:
        await stream.aclose()


async def test_model_limit_uses_reserved_final_answer_without_extra_review(setup, monkeypatch):
    calls = []
    async def chat(settings, config, key, messages, **kwargs):
        calls.append(kwargs.get('tools'))
        if len(calls) <= 93:
            return response(calls=[(f'discover-{len(calls)}', 'load_tools', {'groups': ['work']})])
        assert not kwargs.get('tools')
        return response('<!--noria:{"remaining":["具体工作查询尚未完成"]}-->\n这次尚未完成具体查询，你可以继续说明希望优先查哪一项。')
    provider(monkeypatch, chat)
    result, stored = await run(setup)
    assert len(calls) == 94, result
    assert stored['taskBudget']['models'] == 94 and stored['taskBudget']['tools'] == 0
    assert stored['taskBudget']['endedAt']
    assert not stored.get('deliveryRepairs')
    assert result['job']['taskOutcome']['state'] == 'blocked'


@pytest.mark.parametrize('who', ['employee', 'admin'])
async def test_preparation_hard_deadline_ends_without_model_or_waiting_nodes(setup, monkeypatch, who):
    monkeypatch.setattr(policies, 'DEFAULT', Policy(seconds=0, reserve_seconds=0))
    async def never(*args, **kwargs):
        raise AssertionError('Provider must not be called after deadline')
    provider(monkeypatch, never)
    result, stored = await run(setup, who=who)
    assert result['job']['taskOutcome']['state'] == 'blocked', result
    assert stored['taskBudget']['models'] == 0
    assert stored['taskBudget']['endedAt']
    assert result['reply'] and not result['job']['error']
    assert all(node['state'] not in ('running', 'waiting', 'retry_wait') for node in result['job']['nodes'])


@pytest.mark.parametrize('stale', [False, True])
async def test_hard_stop_keeps_authorized_partial_reply_and_rejects_stale_prefix(setup, monkeypatch, stale):
    from _support.agent.business_actions import runtime
    from app.tasks.nodes.node_execution import initialize
    from app.tasks.lease import lease
    from app.tasks.feedback.reply_stream import source_snapshot
    from app.agent.completion.recovery.budget import deliver
    context, sent = await runtime(setup)
    context.node_retry = True
    await initialize(context, 'partial')
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        job.feedback = {**job.feedback, 'replyStreamCall': 'call', 'replyStream': {'version': 2, 'generation': 1, 'state': 'streaming', 'text': ''}}
        source = source_snapshot(context, job)
    async def partial(*args):
        return {'attempt': 0, 'fence': context.fence - int(stale), 'callId': 'call', 'generation': 1, 'source': source,
                'text': '这是已经输出的安全正文片段。', 'sealed': False}
    monkeypatch.setattr('app.tasks.feedback.reply_stream.temporary_snapshot', partial)
    await deliver(context, 'time')
    result = (await setup[3]['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert ('已经输出的安全正文片段' in result['reply']) is not stale
    assert result['job']['taskOutcome']['state'] == ('blocked' if stale else 'partial')


async def test_long_task_does_not_block_other_user_and_cancel_wins(setup, monkeypatch):
    from app.tasks.runtime.cancellation import cancel_job, CancelJob
    from app.tasks.budget.service import ensure
    from app.tasks.runtime.cancellation import run_until_interrupted
    from app.tasks.context import LostLease
    from app.tasks.lease import lease
    from _support.agent.business_actions import runtime
    context, _ = await runtime(setup)
    context2, _ = await runtime(setup, who='peer')
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        ensure(job, context)
    began = asyncio.Event()
    closed = asyncio.Event()
    async def wait():
        began.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()
    task = asyncio.create_task(run_until_interrupted(context, wait()))
    await began.wait()
    from app.agent.runtime.model import reserve_call
    await asyncio.wait_for(reserve_call(context2, 'asr'), timeout=2)
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        await cancel_job(db, actor, job.id, CancelJob(expectedAttempt=job.attempt, expectedFence=job.fence))
    with pytest.raises(LostLease):
        await asyncio.wait_for(task, timeout=4)
    assert closed.is_set()
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert job.state == 'cancelled' and job.result['taskBudget']['endedAt']
