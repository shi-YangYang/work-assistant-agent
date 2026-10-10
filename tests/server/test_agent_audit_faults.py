"""Spec 059 destructive cases. Synthetic fixtures, unchanged application code."""
import asyncio
import json
from pathlib import Path
import sys
from uuid import uuid4

import httpx
import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/company/web-acceptance/agent-audit'))
from faults import evidence, isolated_url
from app.modules.memories.models import AssistantMemory
from app.modules.members.models import Member
from app.modules.messages.models import Message
from app.modules.work.models import WorkItem
from app.tasks.models import Job
from app.tasks.processing.handlers import process_job
from app.tasks.runtime.queue import claim
from test_agent_budget_flow import provider, response, run

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('cycle', [1, 2, 3])
async def test_fixed_tool_cycles_end_with_default_budget_without_writes(setup, monkeypatch, cycle):
    """Force A / A-B / A-B-C loops without reducing production limits."""
    calls, logical, final_calls = [], [], []
    tools = [('find_work_items', {'query': '没有变化的目标'}),
             ('query_report_obligations', {'kind': 'daily'}),
             ('query_reports', {'kind': 'daily'})][:cycle]
    async def chat(settings, config, key, messages, **kwargs):
        calls.append(len(messages))
        if len(calls) == 1:
            return response(calls=[('catalog', 'load_tools', {'groups': ['work', 'reports']})])
        if not kwargs.get('tools'):
            final_calls.append(1)
            return response('<!--noria:{"remaining":["目标不存在，停止查询"]}-->\n没有找到目标，已停止重复查询。')
        name, args = tools[len(logical) % cycle]
        logical.append(name)
        return response(calls=[(f'loop-{len(logical)}', name, args)])
    provider(monkeypatch, chat)
    result, stored = await run(setup, '查找当前工作与汇报中的目标')
    async with setup[1]() as db:
        writes = await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == setup[2]['employee'].id))
    row = {'cycle': cycle, 'modelCalls': len(calls), 'modelToolRequests': len(logical),
           'logicalTools': stored['taskBudget']['tools'], 'finalModelCalls': len(final_calls),
           'writes': writes, 'outcome': result['job']['taskOutcome']['state'],
           'sequence': logical, 'reply': result['reply']}
    evidence(f'loop-{cycle}', row)
    assert stored['taskBudget']['endedAt'] and len(calls) <= 96
    assert len(logical) <= 12 and stored['taskBudget']['tools'] <= 12 and writes == 0
    assert final_calls == [1] and result['job']['taskOutcome']['state'] == 'blocked'
    assert not any(node['state'] in ('running', 'waiting', 'retry_wait') for node in result['job']['nodes'])


async def test_seven_repeated_model_memory_saves_record_one_fact(setup):
    from test_memory_tool_flow import MemoryModel
    from test_response_delivery import run as run_model
    model = MemoryModel(model='controlled', api_key='unused', repeat_count=7)
    result, stored = await run_model(setup, model, '我喜欢吃米饭')
    current = (await setup[3]['employee'].get('/api/v1/assistant/memory')).json()
    evidence('memory-seven', {'modelCalls': model.calls, 'modelToolRequests': len(model.receipts),
                            'receipts': model.receipts, 'memoryRevision': current['revision'],
                            'memoryText': current['markdown'], 'jobOutcome': result['job']['state'],
                            'taskOutcome': result['job']['taskOutcome'], 'reply': result['reply'],
                            'durableMemoryOperations': len(stored.get('memoryOperations', []))})
    assert current['markdown'].count('喜欢吃米饭') == 1 and current['revision'] == 1
    assert len(stored['memoryOperations']) == 1
    assert sum(item.get('state') == 'succeeded' for item in model.receipts) == 1
    assert result['job']['taskOutcome']['state'] == 'completed'


async def test_parallel_same_memory_patch_different_call_ids_has_one_revision(setup):
    from test_assistant_memory import context_for, apply
    context, _ = await context_for(setup, '我喜欢吃米饭')
    results = await asyncio.gather(*(apply(context, call_id=f'parallel-{index}', old='', new='喜欢吃米饭。',
                                         evidence='我喜欢吃米饭', explicit=False) for index in range(7)), return_exceptions=True)
    current = (await setup[3]['employee'].get('/api/v1/assistant/memory')).json()
    evidence('memory-parallel', {'attempts': 7, 'results': [value if isinstance(value, dict) else type(value).__name__ for value in results],
                                 'revision': current['revision'], 'markdown': current['markdown']})
    assert not any(isinstance(value, BaseException) for value in results)
    assert current['revision'] == 1 and current['markdown'].count('喜欢吃米饭') == 1


async def test_owned_database_disconnection_and_idempotent_recovery(setup, monkeypatch, caplog):
    import test_infrastructure_failures as existing
    monkeypatch.setattr(existing, 'isolated_url', isolated_url)
    await existing.test_database_disconnect_rolls_back_partial_write_and_recovers(setup, caplog)


@pytest.mark.parametrize('fault', ['permission', 'capacity'])
async def test_owned_media_failure_and_cleanup(setup, monkeypatch, caplog, fault):
    import test_infrastructure_failures as existing
    monkeypatch.setattr(existing, 'isolated_url', isolated_url)
    await existing.test_media_write_failure_leaves_no_file_or_row_and_recovers(setup, monkeypatch, caplog, fault)


async def test_owned_worker_sigkill_and_real_lease_recovery(setup, monkeypatch, tmp_path):
    import test_process_worker_recovery as existing
    isolated_url(setup[0])
    source = Path(existing.__file__).with_name('full_system_worker_probe.py').read_text()
    old = "('-csearch_path=spec044_', '-csearch_path=spec054_')"
    assert old in source
    # The prior probe only names old suites. Adapt its test-only guard while
    # preserving every crash barrier, real lease duration and assertion.
    schema_option = isolated_url(setup[0]).query['options']
    (tmp_path / 'full_system_worker_probe.py').write_text(source.replace(old, repr((schema_option,))))
    monkeypatch.setattr(existing, '__file__', str(tmp_path / 'test_process_worker_recovery.py'))
    await existing.test_owned_worker_sigkill_before_write_after_commit_and_after_delivery(setup, tmp_path)


@pytest.mark.parametrize('concurrency', [1, 5, 10])
async def test_isolated_users_mixed_tasks_do_not_cross_outputs(setup, concurrency):
    from test_tool_catalog import CatalogModel
    from test_memory_tool_flow import MemoryModel
    from test_response_delivery import DeliveryModel
    settings, sessions, users, clients = setup
    isolated_url(settings)
    actors, http_clients, expected = [], [], []
    try:
        async with sessions.begin() as db:
            for index in range(concurrency):
                actor = Member(company_id=users['employee'].company_id, username='audit_' + uuid4().hex[:14],
                               name='并发合成用户' + str(index), role='employee', password_hash=users['employee'].password_hash)
                db.add(actor)
                await db.flush()
                actors.append(actor)
        for index, actor in enumerate(actors):
            client = httpx.AsyncClient(transport=httpx.ASGITransport(app=clients['employee']._transport.app),
                                       base_url='http://test', headers={'Origin': 'http://test'})
            login = await client.post('/api/v1/auth/login', json={'username': actor.username, 'password': 'controlled-test-password'})
            assert login.status_code == 200
            client.headers['X-CSRF-Token'] = login.json()['csrf']
            http_clients.append(client)
            text = '我喜欢吃米饭' if index % 3 == 1 else '查询我的工作' if index % 3 == 2 else '你好'
            answer = f'独立回答{index}'
            expected.append(answer if index % 3 != 1 else '记住啦。')
            fake = (MemoryModel(model='controlled', api_key='unused') if index % 3 == 1 else
                    CatalogModel(model='controlled', api_key='unused', answer=answer) if index % 3 == 2 else
                    DeliveryModel(model='controlled', api_key='unused', answer=answer))
            sent = await client.post('/api/v1/messages', json={'text': text, 'newConversation': True}, headers={'Idempotency-Key': str(uuid4())})
            assert sent.status_code == 202
            actor.audit_sent, actor.audit_fake = sent.json(), fake
        async def work(actor):
            job = await claim(sessions, actor.id)
            assert job.owner_id == actor.id
            async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
                await process_job(job, sessions, settings, saver, model=actor.audit_fake)
        await asyncio.gather(*(work(actor) for actor in actors))
        observed = []
        for index, (client, actor) in enumerate(zip(http_clients, actors)):
            reply = await client.get('/api/v1/messages/' + actor.audit_sent['messageId'])
            value = reply.json()
            observed.append({'owner': index, 'state': value['job']['state'], 'reply': value['reply']})
            evidence(f'users-{concurrency}-first-result-{index}', value)
            assert value['reply'] == expected[index] and value['job']['taskOutcome']['state'] == 'completed'
            if concurrency > 1:
                denied = await client.get('/api/v1/messages/' + actors[(index + 1) % concurrency].audit_sent['messageId'])
                assert denied.status_code == 404
        async with sessions() as db:
            count = await db.scalar(select(func.count()).select_from(Message).where(Message.owner_id.in_([actor.id for actor in actors])))
            memories = (await db.scalars(select(AssistantMemory).where(AssistantMemory.owner_id.in_([actor.id for actor in actors])))).all()
        evidence(f'users-{concurrency}', {'concurrentUsers': concurrency, 'messages': count,
                                        'savedMemoryDocuments': sum(bool(row.document.get('markdown')) for row in memories), 'outcomes': observed})
        assert count == concurrency
    finally:
        for client in http_clients:
            await client.aclose()


async def test_owned_redis_capacity_restart_and_new_publication(monkeypatch):
    """Only an exact owned disposable container may receive destructive commands."""
    import os
    import subprocess
    from pathlib import Path
    from app.tasks.streaming.redis_store import RedisReplyStore
    from app.tasks.streaming.protocol import Identity
    from test_reply_stream_transport import test_real_capacity_refusal_and_redis_restart, value
    path = os.getenv('PAA_AGENT_FAULT_RESOURCES') or os.getenv('SPEC059_OWNED_RESOURCES')
    if not path:
        pytest.skip('Requires an owned disposable Redis container')
    owned = json.loads(Path(path).read_text())
    inspection = json.loads(subprocess.check_output(['docker', 'inspect', owned['redisName']]))[0]
    assert inspection['Id'] == owned['redisId']
    assert inspection['Config']['Labels'].get(owned.get('labelKey', 'noria.spec059')) == owned.get('labelValue', owned['run'])
    assert inspection['HostConfig']['PortBindings']['6379/tcp'][0]['HostIp'] == '127.0.0.1'
    from urllib.parse import urlsplit
    assert int(inspection['HostConfig']['PortBindings']['6379/tcp'][0]['HostPort']) == urlsplit(owned['redisUrl']).port
    assert owned['redisUrl'].startswith('redis://127.0.0.1:')
    monkeypatch.setenv('PAA_REPLY_STREAM_FAULT_URL', owned['redisUrl'])
    monkeypatch.delenv('PAA_REPLY_STREAM_FAULT_CONTAINER', raising=False)
    await test_real_capacity_refusal_and_redis_restart()
    store = RedisReplyStore(owned['redisUrl'], namespace='spec059:fault:' + owned['run'])
    identity = Identity('owned', 'owner', 'redis-restart', 0, 1)
    try:
        await store.publish(identity, value(identity, 1, 'before restart'), {'seq': 1})
        process = await asyncio.create_subprocess_exec('docker', 'restart', owned['redisId'], stdout=asyncio.subprocess.DEVNULL)
        assert await process.wait() == 0
        async with asyncio.timeout(10):
            while True:
                try:
                    await store.client.ping()
                    break
                except Exception:
                    await asyncio.sleep(.1)
        assert await store.snapshot(identity) is None
        await store.publish(identity, value(identity, 2, 'after restart'), {'seq': 2})
        assert (await store.snapshot(identity))['text'] == 'after restart'
        evidence('redis-restart', {'capacityRefused': True, 'restartDropsTransientSnapshot': True,
                                   'newPublicationSucceeds': True, 'ownedContainer': owned['redisId']})
    finally:
        await store.client.delete(*store.keys(identity))
        await store.close()


async def test_rejected_write_cannot_claim_success_through_current_graph(setup, monkeypatch):
    """Observe a forced false claim after a real authorization rejection."""
    calls, graph_calls, intent_calls, receipts = [], [], [], []
    async def chat(settings, config, key, messages, **kwargs):
        calls.append(1)
        try:
            payload = json.loads(messages[-1]['content'])
        except (ValueError, TypeError, KeyError):
            payload = {}
        if isinstance(payload, dict) and 'proposedOperation' in payload:
            intent_calls.append(1)
            return response(json.dumps({'allowed': False, 'quote': '', 'reason': '用户明确要求不要创建', 'failureKind': 'not_requested', 'notRequested': True}))
        graph_calls.append(1)
        for item in messages:
            if item.get('role') == 'tool' and item.get('tool_call_id') == 'denied-write':
                if item['content'] not in receipts:
                    receipts.append(item['content'])
        if len(graph_calls) == 1:
            return response(calls=[('catalog', 'load_tools', {'groups': ['work']})])
        if len(graph_calls) == 2:
            return response(calls=[('denied-write', 'execute_business_action', {
                'step': 1, 'action': 'create_work', 'changes': {'title': '不应创建'}})])
        return response('已创建工作。')
    provider(monkeypatch, chat)
    async def configured(*args):
        return {'baseUrl': 'https://controlled.invalid/v1', 'model': 'controlled', 'parameters': {}, 'streaming': True}, 'test'
    monkeypatch.setattr('app.modules.model_services.bindings.resolve_bound', configured)
    result, stored = await run(setup, '同事说“创建工作”，我只是举例，不要创建。')
    async with setup[1]() as db:
        writes = await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == setup[2]['employee'].id))
    row = {'modelCalls': len(calls), 'graphModelCalls': len(graph_calls), 'intentModelCalls': len(intent_calls),
           'modelToolRequests': 2, 'businessToolRequests': 1, 'businessToolResults': receipts,
           'actions': len(result['actions']), 'workWrites': writes, 'reply': result['reply'],
           'outcome': result['job']['taskOutcome'], 'operationFeedback': result['job']['operationFeedback'],
           'budget': stored.get('taskBudget')}
    evidence('rejected-write-current-graph', row)
    assert len(graph_calls) >= 3 and receipts, row
    assert writes == 0 and not result['actions']
    # Complete prose is intentionally retained; this synthetic model still lies.
    assert result['reply'] == '已创建工作。', row
    assert result['job']['taskOutcome']['state'] != 'needs_input'
    assert all(item['category'] == 'not_requested' for item in stored['toolOutcomes'])
    assert not result['job']['taskOutcome']['completed']
