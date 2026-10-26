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
from app.agent.tools.business.work import get_work_item
from app.tasks.context import BudgetExceeded, LostLease
from app.tasks.models import Job
from app.tasks.nodes.node_execution import initialize
from app.tasks.processing.handlers import process_job
from app.tasks.runtime.queue import claim
from _support.agent.business_actions import create, finish, runtime
from _support.http.company import send
from _support.agent.response_delivery import DeliveryModel, run
from _support.agent.work_conflict_refresh import tool_request
from _support.agent.tool_catalog import CatalogModel

pytestmark = pytest.mark.asyncio


def fake(**kwargs):
    return CatalogModel(model='controlled-catalog', api_key='no-network', **kwargs)


async def test_ordinary_prose_exposes_catalog_and_question_once_and_keeps_clock_role_mode(setup):
    model = fake(scenario='prose', answer='完整回答。')
    result, stored = await run(setup, model, '介绍一下你的作用')
    assert result['reply'] == '完整回答。' and model.calls == 1
    assert model.requests == [{'tools': ['load_tools', 'request_user_input', 'web_search'], 'tool_choice': 'auto'}]
    assert not stored.get('toolCatalog') and not stored.get('deliveryRepairs')
    assert result['job']['taskOutcome']['state'] == 'completed'
    assert '当前请求时间' in model.systems[0] and 'Asia/Shanghai' in model.systems[0]
    assert '当前执行权限' in model.systems[0] and '员工：' in model.systems[0]
    # Search is immediately usable; its privacy and source rules accompany it once.
    from app.agent.prompts.main import POLICIES
    assert model.systems[0].count(POLICIES['research']) == 1
    assert all(policy not in model.systems[0] for group, policy in POLICIES.items() if group != 'research')
    assert '缺用户选择直接 request_user_input' in model.systems[0]
    assert '内部ID、转写字段名、行号/字符范围' in model.systems[0]
    assert '正文不汇报读取范围或完整性检查' in model.systems[0]
    assert '保留原文数字、时间、否定及条件' in model.systems[0]
    from langchain_core.utils.function_calling import convert_to_openai_tool
    from app.agent.tools.control.questions import request_user_input
    assert model.schemas[0][1] == convert_to_openai_tool(request_user_input)
    assert len(json.dumps(model.schemas[0][0], ensure_ascii=False)) < 1800
    parameters = model.schemas[0][0]['function']['parameters']
    assert '_flow' in parameters['required']
    assert parameters['properties']['_flow'] == {'type': 'object', 'required': ['route', 'need']}


async def test_load_read_then_prose_exposes_only_requested_full_schemas(setup):
    model = fake(answer='当前没有工作。')
    result, stored = await run(setup, model, '查我的工作')
    assert result['reply'] == '当前没有工作。' and model.calls == 3
    assert model.requests[0]['tools'] == ['load_tools', 'request_user_input', 'web_search']
    assert set(model.requests[1]['tools']) == {'load_tools', 'request_user_input', 'web_search'} | (GROUPS['work'] - {'find_team_members', 'query_team_business', 'read_team_source', 'propose_followup'})
    assert '工具定义' in model.schemas[0][0]['function']['description']
    assert 'bodyEdits' in model.schemas[1][1]['function'].get('description', '') or any('bodyEdits' in str(tool) for tool in model.schemas[1])
    assert '工作：' not in model.systems[0] and '工作：' in model.systems[1]
    assert '未勾选仅表示未完成/未勾选，不代表尚未开始' in model.systems[1]
    assert '报告：' not in model.systems[1]
    assert stored['toolCatalog']['groups'] == ['work']
    assert len([node for node in result['job']['nodes'] if node['kind'] == 'tool']) == 1
    assert not stored.get('deliveryRepairs')

    # Reads keep the v8 fact-need contract after catalog loading. Legacy calls
    # lacking it still finish without a repair round.
    assert '_flow' in model.schemas[0][0]['function']['parameters']['required']
    from app.agent.runtime.decision_flow import exploratory
    for schema in model.schemas[1]:
        function = schema['function']
        required = function['parameters'].get('required', [])
        assert ('_flow' in required) == exploratory(function['name'])
        if exploratory(function['name']):
            assert function['parameters']['properties']['_flow']['required'] == ['route', 'need']
    assert all(call['route'] == 'unknown' for call in stored['decisionFlow']['calls'].values())


async def test_first_search_remembers_research_and_offers_fetch_without_catalog_round(setup, monkeypatch):
    from app.agent.prompts.main import POLICIES
    from app.agent.tools.resources import web

    class SearchModel(CatalogModel):
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            self.calls += 1
            names = [tool['function']['name'] for tool in kwargs['tools']]
            self.requests.append(names)
            assert messages[0].text.count(POLICIES['research']) == 1
            if self.calls == 1:
                assert names == ['load_tools', 'request_user_input', 'web_search']
                answer = AIMessage(content='', tool_calls=[{'id': 'direct-search', 'name': 'web_search',
                    'args': {'query': 'Python documentation', '_flow': {'route': 'fact', 'need': '官方文档入口'}}}])
            else:
                assert self.calls == 2 and 'web_fetch' in names
                assert [message.name for message in messages if isinstance(message, ToolMessage)] == ['web_search']
                answer = AIMessage(content='<!--noria:{}-->\n已找到公开文档入口。')
            return ChatResult(generations=[ChatGeneration(message=answer)])

    search = AsyncMock(return_value={'items': [{'url': 'https://docs.python.org/', 'title': 'Python documentation',
        'snippet': 'Official Python documentation', 'evidenceType': 'search_snippet'}]})
    monkeypatch.setattr(web.web_research, 'web_search', search)
    model = SearchModel(model='controlled-search', api_key='no-network')
    result, stored = await run(setup, model, '查找 Python 官方文档入口')
    assert result['reply'] == '已找到公开文档入口。' and model.calls == 2
    assert result['job']['taskOutcome']['state'] == 'completed'
    search.assert_awaited_once_with('Python documentation', domains=None)
    assert stored['toolCatalog']['groups'] == ['research']
    assert [node['label'] for node in stored['nodeExecution']['nodes'] if node['kind'] == 'tool'] == ['搜索资料']
    context, _ = await runtime(setup, '新的独立请求')
    assert loaded_groups(context, SimpleNamespace(result=stored)) == []
    assert 'web_fetch' not in visible_tools(context, [])


async def test_decision_closed_model_does_not_reoffer_default_search(setup):
    from app.agent.harness import build_graph
    from app.agent.prompts.main import POLICIES
    from app.agent.runtime import decision_flow

    context, _ = await runtime(setup, '已整理完毕，交付答复')
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        value = decision_flow.current(context, job)
        value['phase'] = 'executing'
        decision_flow.save(job, value)
    model = fake(scenario='prose', answer='已整理完毕。')
    await build_graph(context.settings, None, context, model).ainvoke(
        {'messages': [HumanMessage(content='已整理完毕，交付答复')]}, context=context)
    assert model.calls == 1
    assert not {'web_search', 'web_fetch'} & set(model.requests[0]['tools'])
    assert POLICIES['research'] not in model.systems[0]


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


async def test_known_tool_call_registers_capability_but_preserves_cached_node_and_acl(setup):
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
    from app.agent.tools.catalog import remember_call_capability
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        remember_call_capability(context, job, {'name': 'read_execution', 'args': {}})
        assert loaded_groups(context, job) == ['documents']
        assert 'read_execution' in visible_tools(context, loaded_groups(context, job))


async def test_loaded_document_policy_reaches_actual_model_input(setup):
    model = fake(scenario='files', answer='已说明材料范围。')
    result, stored = await run(setup, model, '请读取此前的材料')
    assert result['reply'] == '已说明材料范围。' and model.calls == 2
    assert stored['toolCatalog']['groups'] == ['documents']
    assert 'attachmentSummary' not in model.systems[0]
    assert 'attachmentSummary' in model.systems[1]
    assert '缺少某事实不代表来源冲突' in model.systems[1]


async def test_files_group_locates_prior_uploads_without_loading_documents_or_granting_access(setup):
    from sqlalchemy import func, select
    from _support.http.management import conversation, message
    from _support.materials.documents import running_context, upload
    from app.agent.tools.resources.documents import find_documents
    from app.agent.tools.resources.messages import get_message_context
    from app.modules.attachments.models import DocumentChunk

    settings, sessions, users, clients = setup
    source_ids = []
    for who in ('employee', 'peer'):
        conv = await conversation(clients[who])
        item = await upload(clients[who], 'original.csv', b'name,value\na,7')
        sent = await message(clients[who], conv, 'Keep this original', [item['id']])
        source_ids.append((conv, item, sent))
        await finish(await running_context(settings, sessions, users[who], sent))
    conv, item, original = source_ids[0]
    sent = await message(clients['employee'], conv, 'Inspect the earlier table')
    context = await running_context(settings, sessions, users['employee'], sent)
    context.settings = replace(settings, sandbox_url='http://sandbox.invalid', sandbox_token='test-only')
    invoke = SimpleNamespace(context=context)
    loaded = json.loads(await load_tools.coroutine(['files'], invoke))
    assert loaded['groups'] == ['files']
    assert {'get_message_context', 'find_documents'} <= set(loaded['tools'])
    directory = json.loads(await find_documents.coroutine('', invoke))
    assert [entry['id'] for entry in directory['items']] == [item['id']]
    source = json.loads(await get_message_context.coroutine(original['messageId'], invoke))
    assert [entry['id'] for entry in source['documents']] == [item['id']]
    foreign_item, foreign_message = source_ids[1][1:]
    denied = json.loads(await find_documents.coroutine('', invoke, attachment_id=foreign_item['id']))
    assert denied['error'] == 'document_reference_unavailable'
    assert foreign_item['id'] not in str(denied)
    denied_message = await get_message_context.coroutine(foreign_message['messageId'], invoke)
    assert foreign_item['id'] not in denied_message and '无权查看' in denied_message
    async with sessions() as db:
        assert not await db.scalar(select(func.count()).select_from(DocumentChunk).where(
            DocumentChunk.attachment_id.in_([item['id'], foreign_item['id']])))
        assert loaded_groups(context, await db.get(Job, context.job_id)) == ['files']


async def test_closed_discovery_returns_only_currently_available_tools(setup):
    from app.agent.runtime import decision_flow
    context, _ = await runtime(setup, '已整理好，保存结果')
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        value = decision_flow.current(context, job)
        value['phase'] = 'executing'
        decision_flow.save(job, value)
    result = json.loads(await load_tools.coroutine(['research', 'documents'], SimpleNamespace(context=context)))
    assert 'save_deliverable' in result['tools']
    assert not {'web_search', 'web_fetch', 'read_document', 'find_documents'} & set(result['tools'])


@pytest.mark.parametrize('groups', [[], ['work'], ['reports'], ['work', 'reports']])
async def test_shared_business_contract_preserves_cross_group_direct_actions(groups):
    from app.agent.tools.business.actions import execute_business_action
    from langchain_core.utils.function_calling import convert_to_openai_tool
    context = SimpleNamespace(role='employee', settings=SimpleNamespace(sandbox_url='', sandbox_token=''))
    visible = visible_tools(context, groups)
    assert ('execute_business_action' in visible) == bool(groups)
    schema = convert_to_openai_tool(execute_business_action)['function']
    parameters = schema['parameters']['properties']
    assert set(parameters['action']['enum']) == {
        'create_work', 'update_work', 'delete_work', 'generate_report', 'edit_report', 'submit_report', 'delete_report'}
    assert {'step', 'task_item_id', 'target_id', 'expected_revision', 'changes', 'report_date',
            'report_kind', 'submit_after', 'source_tokens', 'requires_step', 'copy_index',
            'deliverable_id', 'deliverable_revision', 'item_id', 'shared_attachment_ids'} <= parameters.keys()
    assert all(term in schema['description'] for term in ('Monday-Sunday', 'bodyEdits', 'materialIds',
        'review-before-submit', 'get_business_actions', 'source_tokens', 'never guess', 'compound items'))
