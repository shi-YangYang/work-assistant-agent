"""Real tool wrappers retain failure authority; repair is opt-in, not inferred prose."""
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.agent.tool_results import failed_result, recoverable_result


class Sessions:
    @asynccontextmanager
    async def begin(self):
        yield SimpleNamespace()

    __call__ = begin


@pytest.mark.asyncio
@pytest.mark.parametrize('entry', ['business', 'generate_image', 'save_deliverable', 'read_deliverable',
    'memory', 'python', 'execution', 'builtin', 'members', 'team', 'source', 'question'])
@pytest.mark.parametrize('status', [403, 409])
async def test_real_http_wrappers_preserve_denial_and_conflict(monkeypatch, entry, status):
    from app.agent.tools.business import actions, team
    from app.agent.tools.resources import deliverables, images
    from app.agent.tools.sandbox import execution, common
    from app.agent.tools import memory
    from app.agent.tools.control import questions
    from app.agent.actions import interactions
    from app.tasks import lease as leases

    job = SimpleNamespace(kind='message', target_id='message', result={})
    actor = SimpleNamespace()
    context = SimpleNamespace(sessions=Sessions(), deliverable_reads={}, memory_snapshot=None)
    runtime = SimpleNamespace(context=context, tool_call_id='actual-wrapper')
    denial = HTTPException(status, {'code': 'forbidden' if status == 403 else 'revision_conflict', 'message': '不可访问' if status == 403 else '版本已变化'})
    fail = AsyncMock(side_effect=denial)
    for module in (actions, team, deliverables, memory, leases):
        monkeypatch.setattr(module, 'lease', AsyncMock(return_value=(job, actor)))
    monkeypatch.setattr(deliverables, 'owned', AsyncMock(return_value=SimpleNamespace(conversation_id='conversation')))
    from app.security import ownership
    monkeypatch.setattr(ownership, 'owned', AsyncMock(return_value=SimpleNamespace(conversation_id='conversation')))
    monkeypatch.setattr(memory.service, 'conflict_context', AsyncMock(return_value={}))
    if entry == 'business':
        monkeypatch.setattr(actions, 'actions_execute', fail)
        result = await actions.execute_business_action.coroutine(step=1, action='create_work', runtime=runtime)
    elif entry == 'generate_image':
        monkeypatch.setattr(images, 'generate_batch', fail)
        result = await images.generate_image.coroutine(runtime)
    elif entry == 'save_deliverable':
        monkeypatch.setattr(deliverables, 'save', fail)
        result = await deliverables.save_deliverable.coroutine('标题', '正文', runtime)
    elif entry == 'read_deliverable':
        monkeypatch.setattr(deliverables, 'get_deliverable', fail)
        result = await deliverables.read_deliverable.coroutine(runtime, deliverable_id='actual')
    elif entry == 'memory':
        monkeypatch.setattr(memory.service, 'change', fail)
        result = await memory.save_memory.coroutine('喜欢米饭', '我喜欢米饭', runtime)
    elif entry == 'python':
        monkeypatch.setattr(execution, 'execute', fail)
        result = await execution.run_python.coroutine('print(1)', '计算', runtime)
    elif entry == 'execution':
        from app.modules.executions import queries
        monkeypatch.setattr(queries, 'read_executions', fail)
        result = await execution.read_execution.coroutine(runtime)
    elif entry == 'builtin':
        monkeypatch.setattr(common, 'execute', fail)
        monkeypatch.setattr(common, 'builtin_request', lambda name, arguments: {'name': name, 'arguments': arguments})
        result = await common.invoke(runtime, 'inspect_table', {}, title='检查表格')
    elif entry == 'members':
        monkeypatch.setattr(team, 'business_find_members', fail)
        result = await team.find_team_members.coroutine('同事', runtime)
    elif entry == 'team':
        monkeypatch.setattr(team, 'business_query_business', fail)
        result = await team.query_team_business.coroutine(runtime)
    elif entry == 'source':
        monkeypatch.setattr(team, 'business_read_source', fail)
        result = await team.read_team_source.coroutine('source', runtime)
    else:
        monkeypatch.setattr(interactions, 'ask', fail)
        result = await questions.request_user_input.coroutine([], runtime)
    value = json.loads(result)
    assert failed_result(value)
    assert value['httpStatus'] == status
    assert value['category'] == ('permission_denied' if status == 403 else 'conflict')
    assert recoverable_result(value) is (status == 409)


@pytest.mark.parametrize('value', [
    {'state': 'failed'}, {'state': 'unavailable'}, {'error': 'unknown'},
    {'state': 'invalid_reference'},
    {'error': {'code': 'forbidden', 'message': '拒绝'}},
    {'category': 'invalid_arguments', 'error': {'category': 'permission_denied'}},
    {'state': 'conflict', 'recovery': {'owner': 'assistant', 'nextAction': 'stop', 'code': 'saved_step_conflict'}},
    {'state': 'failed', 'category': 'invalid_arguments', 'recovery': {'owner': 'user', 'nextAction': 'ask'}},
    {'state': 'conflict', 'recovery': {'owner': 'system', 'nextAction': 'repair'}},
    {'state': 'unknown', 'category': 'invalid_arguments'},
    {'state': 'cancelled', 'category': 'invalid_arguments'},
])
def test_unknown_terminal_nested_denial_and_explicit_stop_do_not_open_recovery(value):
    assert failed_result(value)
    assert not recoverable_result(value)


def test_actual_repair_failure_stop_takes_precedence_over_conflict():
    from app.agent.actions.operations import repair_failure
    assert not recoverable_result(repair_failure('步骤已经完成', code='saved_step_conflict',
        category='conflict', next_action='stop'))
    assert recoverable_result(repair_failure('正文缺失', code='selected_body_missing'))


@pytest.mark.asyncio
async def test_actual_saved_deliverable_step_is_terminal_but_new_version_conflict_can_refresh(setup):
    from app.agent.tools.resources.deliverables import save_deliverable
    from _support.agent.business_actions import runtime
    context, _ = await runtime(setup, '保存方案')
    invoke = SimpleNamespace(context=context)
    first = json.loads(await save_deliverable.coroutine('方案', '原文', invoke))
    conflict = json.loads(await save_deliverable.coroutine('方案', '另一份', invoke))
    assert conflict['state'] == 'conflict' and conflict['code'] == 'saved_deliverable_step'
    assert failed_result(conflict) and not recoverable_result(conflict)
    stale = json.loads(await save_deliverable.coroutine('方案', '更新', invoke,
        deliverable_id=first['id'], expected_revision=0, step=2))
    assert failed_result(stale) and recoverable_result(stale)


@pytest.mark.asyncio
async def test_business_step_saved_during_authorization_has_same_terminal_contract(setup, monkeypatch):
    from app.agent.actions import operations
    from _support.agent.business_actions import runtime
    context, _ = await runtime(setup, '创建第一项工作，再创建第二项工作')
    authorize = operations.authorize_intent
    inserted = False

    async def save_other_request(current, proposal, *, binding=None):
        nonlocal inserted
        if not inserted:
            inserted = True
            committed = await operations.execute(context, step=1, action='create_work', changes={'title': '第一项'})
            assert committed['state'] == 'succeeded'
        return await authorize(current, proposal, binding=binding)

    monkeypatch.setattr(operations, 'authorize_intent', save_other_request)
    result = await operations.execute(context, step=1, action='create_work', changes={'title': '第二项'})
    assert result['state'] == 'conflict' and result['recovery']['code'] == 'saved_step_conflict'
    assert failed_result(result) and not recoverable_result(result)
    works = (await setup[3]['employee'].get('/api/v1/work-items')).json()['items']
    assert [item['title'] for item in works] == ['第一项']


@pytest.mark.asyncio
async def test_authorized_directory_can_repair_bad_id_without_reading_the_bad_source(monkeypatch):
    from app.agent.tools.resources import documents
    monkeypatch.setattr(documents, 'document_directory', AsyncMock(return_value={'items': [{'id': 'authorized'}]}))
    value = json.loads(await documents.unavailable_reference(None, None, None))
    assert failed_result(value) and recoverable_result(value)
    assert value['availableDocuments']['items'] == [{'id': 'authorized'}]


@pytest.mark.asyncio
async def test_unknown_sandbox_failure_does_not_advertise_argument_repair(monkeypatch):
    from app.agent.tools.sandbox import execution
    monkeypatch.setattr(execution, 'execute', AsyncMock(side_effect=ValueError('执行回执丢失')))
    value = json.loads(await execution.run_python.coroutine('print(1)', '计算', SimpleNamespace(context=None)))
    assert failed_result(value) and not recoverable_result(value)


@pytest.mark.parametrize('extra', [{}, {'category': 'not_requested'}, {'category': 'not_requested', 'diagnostic': 'previousTask cancelled，未明确恢复'}])
def test_not_requested_projection_does_not_return_internal_reason(extra):
    from app.tasks.feedback.public import model_result
    result = model_result({'state': 'not_requested', 'message': 'previousTask cancelled，未明确恢复', **extra})
    assert result['message'] == '本次未执行这项操作。'
    assert 'diagnostic' not in result


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 403, 404, 503])
async def test_document_reference_repair_does_not_swallow_access_or_service_failures(monkeypatch, status):
    from app.agent.tools.resources import documents
    from app.modules.attachments import documents as attachments
    context = SimpleNamespace(sessions=Sessions())
    monkeypatch.setattr(documents, 'lease', AsyncMock(return_value=(None, None)))
    monkeypatch.setattr(attachments, 'agent_attachment', AsyncMock(side_effect=HTTPException(status, '文件暂时不可用')))
    directory = AsyncMock(return_value={'items': [{'id': 'authorized'}]})
    monkeypatch.setattr(documents, 'document_directory', directory)
    result = json.loads(await documents.read_document_result(context, 'bad-id'))
    assert recoverable_result(result) is (status == 404)
    if status != 404:
        directory.assert_not_called()
        assert result['httpStatus'] == status
    else:
        directory.assert_awaited_once()


@pytest.mark.asyncio
async def test_image_read_http_denial_is_not_a_reupload_or_argument_repair(monkeypatch):
    from app.agent.tools.resources import image_reads
    current = SimpleNamespace(conversation_id='conversation', created_at=1)
    parent = SimpleNamespace(id='message', access={})
    picture = SimpleNamespace(id='image', kind='image', sha256='hash', extraction_revision=1, message_id='message')
    db = SimpleNamespace(get=AsyncMock(return_value=current), execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [(picture, parent)])))
    @asynccontextmanager
    async def session():
        yield db
    job = SimpleNamespace(kind='message', target_id='message')
    actor = SimpleNamespace(id='owner', company_id='company')
    context = SimpleNamespace(sessions=SimpleNamespace(begin=session), image_sources={}, settings=SimpleNamespace(media_dir=__import__('pathlib').Path('/unused')))
    monkeypatch.setattr(image_reads, 'lease', AsyncMock(return_value=(job, actor)))
    monkeypatch.setattr(image_reads, 'valid', AsyncMock(return_value=True))
    monkeypatch.setattr(image_reads, 'inherit', lambda *args: None)
    monkeypatch.setattr(image_reads, 'remember_sources', AsyncMock())
    monkeypatch.setattr(image_reads, 'image_process', AsyncMock(side_effect=HTTPException(403, '当前不可访问')))
    result = json.loads(await image_reads.read_images.coroutine(SimpleNamespace(context=context), attachment_ids=['image']))
    assert result['httpStatus'] == 403 and result['category'] == 'permission_denied'
    assert not recoverable_result(result)
