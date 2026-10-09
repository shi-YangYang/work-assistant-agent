"""Discovery through real worker/checkpoint/ACL boundaries, without model IO."""
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import Field

from app.agent.runtime.middleware import ToolBoundary
from app.agent.tools.catalog import GROUPS, available_groups, catalog_schema, load_tools, loaded_groups, visible_tools
from app.agent.tools.work import get_work_item
from app.tasks.context import BudgetExceeded, LostLease
from app.tasks.models import Job
from app.tasks.nodes.node_execution import initialize
from app.tasks.processing.handlers import process_job
from app.tasks.runtime.queue import claim
from test_business_actions import create, finish, runtime
from test_company import send
from test_response_delivery import DeliveryModel, run
from test_work_conflict_refresh import tool_request

pytestmark = pytest.mark.asyncio


class CatalogModel(DeliveryModel):
    scenario: str = 'query'
    receipt_only: bool = False
    authorizations: list = Field(default_factory=list)
    schemas: list = Field(default_factory=list)
    systems: list = Field(default_factory=list)

    async def ainvoke(self, input, config=None, *, stop=None, **kwargs):
        if isinstance(input, list) and input and isinstance(input[-1], HumanMessage):
            try:
                payload = json.loads(input[-1].content)
            except (ValueError, TypeError):
                payload = {}
            if payload.get('proposedOperation'):
                self.authorizations.append(payload)
                return AIMessage(content=json.dumps({'allowed': True, 'quote': payload['currentUserText'], 'reason': '', 'receiptOnly': self.receipt_only}))
        return await super().ainvoke(input, config, stop=stop, **kwargs)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        tools = kwargs.get('tools', [])
        names = [tool['function']['name'] for tool in tools]
        self.requests.append({'tools': names, 'tool_choice': kwargs.get('tool_choice')})
        self.schemas.append(tools)
        self.systems.append(messages[0].text)
        prior = [message for message in messages if isinstance(message, ToolMessage)]

        def call(name, args, identifier):
            assert name in names, (name, names)
            return AIMessage(content='', tool_calls=[{'id': identifier, 'name': name, 'args': args}])

        if self.scenario == 'prose':
            answer = AIMessage(content='<!--noria:{}-->\n' + self.answer)
        elif not any(message.name == 'load_tools' for message in prior):
            groups = ['files'] if self.scenario == 'files' else ['work']
            if self.scenario == 'files' and 'files' not in tools[0]['function']['parameters']['properties']['groups']['items']['enum']:
                groups = ['documents']
            answer = call('load_tools', {'groups': groups}, 'load-capability')
        elif self.scenario == 'query' and not any(message.name == 'find_work_items' for message in prior):
            answer = call('find_work_items', {'query': ''}, 'read-work')
        elif self.scenario == 'create' and not any(message.name == 'execute_business_action' for message in prior):
            answer = call('execute_business_action', {'step': 1, 'action': 'create_work', 'changes': {'title': '目录验证工作'}}, 'write-work')
        else:
            answer = AIMessage(content='<!--noria:{}-->\n' + self.answer)
        return ChatResult(generations=[ChatGeneration(message=answer)])


def fake(**kwargs):
    return CatalogModel(model='controlled-catalog', api_key='no-network', **kwargs)


async def test_ordinary_prose_has_only_catalog_once_and_keeps_clock_role_mode(setup):
    model = fake(scenario='prose', answer='完整回答。')
    result, stored = await run(setup, model, '介绍一下你的作用')
    assert result['reply'] == '完整回答。' and model.calls == 1
    assert model.requests == [{'tools': ['load_tools'], 'tool_choice': 'auto'}]
    assert not stored.get('toolCatalog') and not stored.get('deliveryRepairs')
    assert result['job']['taskOutcome']['state'] == 'completed'
    assert '当前请求时间' in model.systems[0] and 'Asia/Shanghai' in model.systems[0]
    assert '当前执行权限' in model.systems[0] and '员工：' in model.systems[0]
    # Wire-size regression only; expression quality is assessed with real samples.
    assert len(model.systems[0]) < 1800
    assert len(json.dumps(model.schemas[0], ensure_ascii=False)) < 1300


async def test_load_read_then_prose_exposes_only_requested_full_schemas(setup):
    model = fake(answer='当前没有工作。')
    result, stored = await run(setup, model, '查我的工作')
    assert result['reply'] == '当前没有工作。' and model.calls == 3
    assert model.requests[0]['tools'] == ['load_tools']
    assert set(model.requests[1]['tools']) == {'load_tools'} | (GROUPS['work'] - {'find_team_members', 'query_team_business', 'read_team_source', 'propose_followup'})
    assert '工具定义' in model.schemas[0][0]['function']['description']
    assert 'bodyEdits' in model.schemas[1][1]['function'].get('description', '') or any('bodyEdits' in str(tool) for tool in model.schemas[1])
    assert '工作：' not in model.systems[0] and '工作：' in model.systems[1]
    assert '报告：' not in model.systems[1]
    assert stored['toolCatalog']['groups'] == ['work']
    assert len([node for node in result['job']['nodes'] if node['kind'] == 'tool']) == 1
    assert not stored.get('deliveryRepairs')


@pytest.mark.parametrize('receipt_only', [False, True])
async def test_load_then_real_write_finishes_with_prose_or_receipt(setup, receipt_only):
    model = fake(scenario='create', receipt_only=receipt_only, answer='工作已保存。')
    result, stored = await run(setup, model, '创建工作“目录验证工作”')
    assert len(result['actions']) == 1 and result['actions'][0]['state'] == 'succeeded'
    works = (await setup[3]['employee'].get('/api/v1/work-items')).json()['items']
    assert len(works) == 1 and works[0]['id'] == result['actions'][0]['objectId']
    assert len(model.authorizations) == 1
    assert model.calls == (2 if receipt_only else 3)
    assert result['job']['taskOutcome']['state'] == 'completed'
    assert len([node for node in result['job']['nodes'] if node['kind'] == 'tool']) == 1
    assert stored['toolCatalog']['groups'] == ['work']
    assert not stored.get('deliveryRepairs')


@pytest.mark.parametrize('enabled', [False, True])
async def test_role_and_sandbox_catalog_filtering_and_loading(setup, enabled):
    context, _ = await runtime(setup, '查询资料', 'admin')
    context.settings = replace(context.settings, sandbox_url='http://sandbox.invalid' if enabled else '', sandbox_token='test-only' if enabled else '')
    result = json.loads(await load_tools.coroutine(['work', 'reports'], SimpleNamespace(context=context)))
    assert 'query_team_business' in result['tools'] and context.role == 'admin'
    schema = catalog_schema(context)['function']
    assert ('files' in schema['parameters']['properties']['groups']['items']['enum']) == enabled
    assert '不能写本人或员工报告' in schema['description']
    files = json.loads(await load_tools.coroutine(['files'], SimpleNamespace(context=context)))
    assert files['state'] == ('loaded' if enabled else 'unavailable')
    employee, _ = await runtime(setup, '查询资料', 'peer')
    loaded = json.loads(await load_tools.coroutine(['work'], SimpleNamespace(context=employee)))
    assert not set(loaded['tools']) & {'find_team_members', 'query_team_business', 'read_team_source', 'propose_followup'}
    request = tool_request(employee, 'query_team_business', {}, 'forged-team')
    handler = AsyncMock()
    with pytest.raises(RuntimeError, match='Tool is not allowed'):
        await ToolBoundary().awrap_tool_call(request, handler)
    handler.assert_not_awaited()


async def test_load_is_idempotent_scope_bound_and_lease_guarded(setup):
    context, _ = await runtime(setup, '查询资料')
    context.node_retry = True
    await initialize(context, 'input-a')
    context.tools = 16
    invoke = SimpleNamespace(context=context)
    first = await load_tools.coroutine(['research', 'documents'], invoke)
    assert first == await load_tools.coroutine(['documents', 'research'], invoke)
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert len(job.result['nodeExecution']['nodes']) == 0 and context.tools == 16
        assert loaded_groups(replace(context), job) == ['research', 'documents']
        assert loaded_groups(replace(context, owner_id=setup[2]['peer'].id), job) == []
        assert loaded_groups(replace(context, company_id=setup[2]['outsider'].company_id), job) == []
    changed = replace(context, fence=context.fence + 1)
    with pytest.raises(LostLease):
        await load_tools.coroutine(['work'], SimpleNamespace(context=changed))
    await initialize(context, 'input-b')
    async with context.sessions() as db:
        assert loaded_groups(context, await db.get(Job, context.job_id)) == []
    await finish(context)
    next_context, _ = await runtime(setup, '新的查询')
    async with next_context.sessions() as db:
        assert loaded_groups(next_context, await db.get(Job, next_context.job_id)) == []


async def test_legacy_tool_call_registers_capability_but_preserves_cached_node_and_acl(setup):
    work = await create(setup[3]['employee'])
    context, _ = await runtime(setup, '读取报价方案')
    context.node_retry = True
    await initialize(context, 'old-checkpoint')
    request = tool_request(context, 'get_work_item', {'work_id': work['id']}, 'old-read')
    calls = []

    async def handler(request):
        calls.append(True)
        return ToolMessage(content=await get_work_item.coroutine(work['id'], SimpleNamespace(context=request.runtime.context)), name='get_work_item', tool_call_id='old-read')

    first = await ToolBoundary().awrap_tool_call(request, handler)
    recovered = replace(context, read_versions={})
    await initialize(recovered, 'old-checkpoint')
    request.runtime.context = recovered
    second = await ToolBoundary().awrap_tool_call(request, handler)
    assert first.content == second.content and len(calls) == 1
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert loaded_groups(recovered, job) == ['work']
        assert len(job.result['nodeExecution']['nodes']) == 1
    other, _ = await runtime(setup, '读取别人的工作', 'peer')
    await load_tools.coroutine(['work'], SimpleNamespace(context=other))
    foreign = await get_work_item.coroutine(work['id'], SimpleNamespace(context=other))
    assert work['title'] not in foreign and work['id'] not in foreign


@pytest.mark.parametrize('after_write', [False, True])
async def test_checkpoint_recovery_keeps_loaded_tools_and_does_not_replay_write(setup, monkeypatch, after_write):
    settings, sessions, users, clients = setup
    sent = await send(clients['employee'], '创建工作“目录验证工作”')
    original = ToolBoundary.awrap_tool_call
    interrupted = False

    async def fail_after_result(self, request, handler):
        nonlocal interrupted
        result = await original(self, request, handler)
        if request.tool_call['name'] == ('execute_business_action' if after_write else 'load_tools') and not interrupted:
            interrupted = True
            raise RuntimeError('controlled crash after durable tool result')
        return result

    monkeypatch.setattr(ToolBoundary, 'awrap_tool_call', fail_after_result)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(await claim(sessions, users['employee'].id), sessions, settings, saver, model=fake(scenario='create'))
        async with sessions() as db:
            job = await db.get(Job, sent['jobId'])
            assert job.state in ('failed', 'awaiting_retry') and job.result['toolCatalog']['groups'] == ['work']
        assert (await clients['employee'].post('/api/v1/jobs/' + sent['jobId'] + '/retry', json={})).status_code == 200
        model = fake(scenario='create', answer='工作已保存。')
        await process_job(await claim(sessions, users['employee'].id), sessions, settings, saver, model=model)
    result = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert result['job']['taskOutcome']['state'] == 'completed', result
    assert len(result['actions']) == 1 and result['actions'][0]['state'] == 'succeeded'
    assert len((await clients['employee'].get('/api/v1/work-items')).json()['items']) == 1
    assert all('execute_business_action' in request['tools'] for request in model.requests)
    assert model.calls == (1 if after_write else 2)


async def test_discovery_keeps_existing_request_and_time_budgets(setup):
    from app.agent.runtime.model import reserve_call
    context, _ = await runtime(setup, '查找资料')
    context.node_retry = True
    await initialize(context, 'discovery-budget')
    from app.tasks.lease import lease
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        job.result = {**job.result, 'taskBudget': {**job.result['taskBudget'], 'models': 96}}
    # Discovery spends no logical tool slot and cannot replenish model requests.
    await load_tools.coroutine(['research'], SimpleNamespace(context=context))
    with pytest.raises(BudgetExceeded):
        await reserve_call(context, 'assistant')
    expired = replace(context, node_deadline=1)
    with pytest.raises(BudgetExceeded):
        await load_tools.coroutine(['work'], SimpleNamespace(context=expired))
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert loaded_groups(context, job) == ['research']
        assert job.result['nodeExecution']['nodes'] == []
        assert job.result['taskBudget']['tools'] == 0 and job.result['taskBudget']['models'] == 96


async def test_disabled_execution_history_has_discoverable_recovery_group(setup):
    context, _ = await runtime(setup, '读取先前执行记录')
    assert 'read_execution' in available_groups(context)['documents']
    from app.agent.tools.catalog import remember_legacy_call
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        remember_legacy_call(context, job, {'name': 'read_execution', 'args': {}})
        assert loaded_groups(context, job) == ['documents']
        assert 'read_execution' in visible_tools(context, loaded_groups(context, job))
