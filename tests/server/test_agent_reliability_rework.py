"""Counterexamples from independent acceptance, with real tool result shapes."""
import asyncio
import dataclasses
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from app.agent.runtime.tool_progress import begin, end, state
from app.agent.runtime.tool_progress.evidence import completed_page, page_scope, request_key, result_key
from app.tasks.feedback.outcomes import derive, record


def job():
    return SimpleNamespace(result={}, state='succeeded', error='')


def test_outcomes_only_resolve_the_same_source_object_and_fields():
    task = job()
    base = {'step': 1, 'deliverable_id': 'plan', 'deliverable_revision': 1}
    first = {**base, 'item_id': 'a', 'changes': {'title': '同名'}}
    second = {**base, 'item_id': 'b', 'changes': {'title': '同名'}}
    record(task, 'create_work', first, {'state': 'failed', 'category': 'invalid_arguments', 'message': 'A 缺正文'})
    record(task, 'create_work', second, {'state': 'succeeded', 'id': 'b'})
    assert derive(task, [{'state': 'succeeded'}])['state'] == 'partial'
    assert task.result['operationFeedback'][0]['message'] == 'A 缺正文'
    record(task, 'create_work', {**first, 'changes': {'title': '同名', 'body': {'content': []}}}, {'state': 'succeeded', 'id': 'a'})
    assert not task.result['operationFeedback'] and derive(task)['state'] == 'completed'
    for other in ({'target_id': 'other', 'changes': {'status': 'done'}}, {'target_id': 'work', 'changes': {'nextStep': '确认'}}):
        task = job()
        record(task, 'update_work', {'step': 1, 'target_id': 'work', 'changes': {'status': 'done'}}, {'state': 'failed', 'category': 'invalid_arguments'})
        record(task, 'update_work', {'step': 1, **other}, {'state': 'succeeded'})
        assert task.result['operationFeedback'] and derive(task)['state'] == 'blocked'


def web_page(**changes):
    return {'url': 'https://example.com/news', 'title': 'page', 'text': 'unchanged', 'offset': 0,
            'endOffset': 9, 'totalChars': 9, 'nextOffset': None, 'truncated': False,
            'evidenceType': 'page_text', 'sourceType': 'public_web', 'untrusted': True, **changes}


def test_web_metadata_and_refresh_do_not_reset_empty_progress():
    journal = state.create('one')
    for index in range(12):
        call = {'name': 'web_fetch', 'args': {'url': 'https://example.com/news', 'refresh': bool(index % 2)}}
        journal, decision = state.admit(journal, str(index), request_key(call), 'same')
        if decision == 'stop':
            break
        journal, _ = state.complete(journal, str(index), result_key(call, web_page(fetchedAt=str(index), cacheHit=bool(index % 2))), 'same')
    assert journal['stopped'] and index < 12
    assert result_key(call, web_page()) != result_key(call, web_page(text='changed'))
    assert result_key(call, web_page()) != result_key(call, web_page(offset=9, endOffset=18))
    assert completed_page(call, web_page())
    search = {'name': 'web_fetch', 'args': {**call['args'], 'find': 'same', 'match_index': 1}}
    assert page_scope(search) != page_scope(call)
    assert completed_page(search, web_page(nextMatchIndex=2)) is None
    assert completed_page(search, web_page(nextMatchIndex=None))


@pytest.mark.asyncio
async def test_web_completed_coverage_and_refresh_are_independent(setup):
    from test_business_actions import runtime
    context, _ = await runtime(setup)
    call = {'name': 'web_fetch', 'args': {'url': 'https://example.com/news'}, 'id': 'one'}
    assert await begin(context, call) is None
    await end(context, call, ToolMessage(tool_call_id='one', content=json.dumps(web_page())))
    assert await begin(context, {**call, 'id': 'empty', 'args': {**call['args'], 'offset': 10}})
    search = {**call, 'id': 'search', 'args': {**call['args'], 'find': 'new', 'match_index': 1}}
    assert await begin(context, search) is None
    refresh = {**call, 'id': 'refresh', 'args': {**call['args'], 'refresh': True}}
    assert await begin(context, refresh) is None
    await end(context, refresh, ToolMessage(tool_call_id='refresh', content=json.dumps(web_page(nextOffset=9, totalChars=18))))
    assert await begin(context, {**call, 'id': 'next', 'args': {**call['args'], 'offset': 9}}) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid', ['mixed_context', 'mixed_finish', 'finish'])
async def test_rejected_batches_and_finish_are_bounded_and_never_execute(setup, monkeypatch, invalid):
    from test_business_actions import runtime
    from app.agent.runtime.middleware import ToolBoundary
    from app.tasks.models import Job
    context, _ = await runtime(setup)
    executed = []
    async def handler(request):
        executed.append(request.tool_call['name'])
        return ToolMessage(tool_call_id=request.tool_call['id'], content='{}')
    async def invalid_reference(*args, **kwargs):
        return '回执不存在'
    monkeypatch.setattr('app.agent.completion.delivery.completion_reference_error', invalid_reference)
    boundary = ToolBoundary()
    for index in range(8):
        first = 'set_task_context' if invalid == 'mixed_context' else 'finish_task'
        calls = [{'id': f'a{index}', 'name': first, 'args': {}}]
        if invalid != 'finish':
            calls.append({'id': f'b{index}', 'name': 'execute_business_action', 'args': {'step': 1, 'action': 'create_work', 'changes': {'title': 'x'}}})
        batch = AIMessage(id=f'batch-{index}', content='', tool_calls=calls)
        for call in calls:
            request = SimpleNamespace(runtime=SimpleNamespace(context=context), tool_call=call, state={'messages': [batch]})
            response = await boundary.awrap_tool_call(request, handler)
            assert response.status == 'error'
        async with context.sessions() as db:
            stored = await db.get(Job, context.job_id)
            if stored.result['toolProgress']['stopped']:
                break
    assert not executed and stored.result['toolProgress']['stopped']
    assert len(stored.result['toolProgress']['calls']) <= 8


@pytest.mark.asyncio
async def test_parallel_admission_and_scope_retry_boundaries(setup):
    from test_business_actions import runtime
    from app.agent.runtime.tool_progress.service import scoped
    from app.tasks.models import Job
    context, _ = await runtime(setup)
    call = {'name': 'save_memory', 'args': {'old': '', 'new': '米饭'}, 'id': 'first'}
    results = await asyncio.gather(*(begin(context, {**call, 'id': str(i)}) for i in range(4)))
    assert results.count(None) == 1
    async with context.sessions() as db:
        stored = await db.get(Job, context.job_id)
        journal = stored.result['toolProgress']
        original_scope = journal['scope']
        assert scoped(dataclasses.replace(context, fence=context.fence + 1), stored)['scope'] == original_scope
        for changed in (dataclasses.replace(context, owner_id='other'), dataclasses.replace(context, company_id='other'),
                        dataclasses.replace(context, node_scope='new-input')):
            assert scoped(changed, stored)['calls'] == []
        stored.attempt += 1
        assert scoped(context, stored)['calls'] == []


@pytest.mark.asyncio
async def test_internal_retry_and_checkpoint_replay_count_once(setup):
    from test_business_actions import runtime
    from app.agent.runtime.tool_nodes import tool_node
    from app.integrations.models.transport import ProviderError
    from app.tasks.models import Job
    from app.tasks.nodes.node_execution import initialize
    context, _ = await runtime(setup)
    context.node_retry = True
    await initialize(context, 'retry-count')
    call = {'name': 'get_work_item', 'id': 'read', 'args': {'work_id': 'synthetic'}}
    batch = AIMessage(content='', id='batch', tool_calls=[call])
    request = SimpleNamespace(tool_call=call, state={'messages': [batch]})
    attempts = []
    async def operation():
        attempts.append(1)
        if len(attempts) == 1:
            raise ProviderError('network', 'temporary')
        return ToolMessage(tool_call_id='read', name=call['name'], content='{"id":"synthetic","revision":1}')
    for _ in range(2):
        assert await begin(context, call) is None
        result = await tool_node(context, request, operation)
        await end(context, call, result)
    async with context.sessions() as db:
        stored = await db.get(Job, context.job_id)
        assert len(stored.result['toolProgress']['calls']) == 1
        assert stored.result['toolProgress']['stalled'] == 0
    assert len(attempts) == 2


def test_same_operation_receipt_is_not_new_progress_when_call_arguments_drift():
    first = {'name': 'execute_business_action', 'args': {'step': 1, 'target_id': 'work'}}
    second = {'name': 'execute_business_action', 'args': {'step': 7, 'target_id': 'work', 'expected_revision': 2}}
    receipt = {'id': 'receipt', 'state': 'succeeded', 'objectId': 'work', 'objectRevision': 2}
    assert result_key(first, receipt) == result_key(second, receipt)
    assert result_key(first, receipt) != result_key(first, {**receipt, 'id': 'copy-receipt', 'objectId': 'new-copy'})


def test_correcting_extra_and_missing_fields_resolves_only_that_request():
    task = job()
    record(task, 'update_work', {'step': 1, 'target_id': 'work', 'changes': {'body': {}, 'status': 'done'}},
           {'state': 'failed', 'category': 'invalid_arguments', 'fieldIssues': [{'field': 'status', 'code': 'not_requested'}]})
    record(task, 'update_work', {'step': 2, 'target_id': 'work', 'changes': {'body': {'new': True}}}, {'state': 'succeeded'})
    assert not task.result['operationFeedback'] and derive(task)['state'] == 'completed'
    record(task, 'update_work', {'step': 3, 'target_id': 'work', 'changes': {'blocker': '等待资源'}},
           {'state': 'failed', 'category': 'invalid_arguments', 'fieldIssues': [{'field': 'status', 'code': 'missing'}]})
    record(task, 'update_work', {'step': 3, 'target_id': 'work', 'changes': {'blocker': '等待资源', 'status': 'blocked'}}, {'state': 'succeeded'})
    assert not task.result['operationFeedback'] and derive(task)['state'] == 'completed'


@pytest.mark.parametrize('action,first,second', [
    ('generate_report', {'report_kind': 'daily', 'report_date': '2026-10-09'}, {'report_kind': 'weekly', 'report_date': '2026-10-10'}),
    ('generate_report', {'report_kind': 'daily', 'report_date': '2026-10-09'}, {'report_kind': 'daily', 'report_date': '2026-10-10'}),
    ('generate_report', {'obligation_id': 'a'}, {'obligation_id': 'b'}),
    ('edit_report', {'target_id': 'report', 'changes': {'completed': '访谈'}}, {'target_id': 'report', 'changes': {'next': '整理'}}),
    ('propose_progress', {'changes': {'title': '甲', 'summary': '未保存'}}, {'changes': {'title': '乙', 'summary': '已保存'}}),
    ('propose_followup', {'changes': {'title': '甲'}}, {'changes': {'title': '乙'}}),
    ('propose_progress', {'target_id': 'work', 'changes': {'summary': '补进展'}}, {'target_id': 'work', 'changes': {'nextStep': '整理'}}),
])
def test_other_business_outcomes_keep_independent_failures_and_resolve_real_recovery(action, first, second):
    task = job()
    failure = {'state': 'failed', 'category': 'invalid_arguments', 'message': '第一项未完成'}
    record(task, action, {'step': 1, **first}, failure)
    record(task, action, {'step': 1, **second}, {'state': 'succeeded', 'id': 'second'})
    assert derive(task, [{'state': 'succeeded'}])['state'] == 'partial'
    assert task.result['operationFeedback'][0]['message'] == '第一项未完成'
    record(task, action, {'step': 3, **first}, {'state': 'succeeded', 'id': 'first'})
    assert not task.result['operationFeedback'] and derive(task)['state'] == 'completed'


def test_weekly_report_recovery_uses_canonical_period():
    task = job()
    record(task, 'generate_report', {'step': 1, 'report_kind': 'weekly', 'report_date': '2026-10-09'},
           {'state': 'failed', 'category': 'invalid_arguments'})
    record(task, 'generate_report', {'step': 2, 'report_kind': 'weekly', 'report_date': '2026-10-05'}, {'state': 'running'})
    assert not task.result['operationFeedback']


def test_default_copy_is_not_identity_and_explicit_item_recovers_changed_create():
    task = job()
    defaults = {'step': 1, 'target_id': '', 'expected_revision': 0, 'report_kind': 'daily', 'report_date': '',
                'obligation_id': '', 'source_tokens': None, 'submit_after': False, 'requires_step': None, 'copy_index': 1,
                'deliverable_id': '', 'deliverable_revision': 0, 'item_id': '', 'shared_attachment_ids': None}
    first = {**defaults, 'task_item_id': 'server-a', 'changes': {'title': '修正前'}}
    record(task, 'create_work', first, {'state': 'failed', 'category': 'invalid_arguments', 'message': '甲未完成'})
    record(task, 'create_work', {**defaults, 'task_item_id': 'server-b', 'changes': {'title': '另一事项'}}, {'state': 'succeeded'})
    assert task.result['operationFeedback'][0]['message'] == '甲未完成'
    record(task, 'create_work', {**first, 'changes': {'title': '修正后', 'body': {'content': []}},
                                'deliverable_id': 'plan', 'deliverable_revision': 1, 'item_id': 'entry-a'}, {'state': 'succeeded'})
    assert not task.result['operationFeedback'] and derive(task)['state'] == 'completed'


def test_existing_source_cannot_be_replaced_even_with_same_task_item():
    task = job()
    first = {'step': 1, 'task_item_id': 'server-a', 'deliverable_id': 'plan', 'deliverable_revision': 1,
             'item_id': 'entry-a', 'changes': {'title': '同名'}}
    record(task, 'create_work', first, {'state': 'failed', 'category': 'invalid_arguments'})
    record(task, 'create_work', {**first, 'item_id': 'entry-b'}, {'state': 'succeeded'})
    assert task.result['operationFeedback']


@pytest.mark.asyncio
async def test_failed_create_recovers_with_explicit_item_after_adding_source(setup):
    from app.agent.tools.actions import execute_business_action
    from app.tasks.models import Job
    from test_business_actions import Judge
    from test_execution_permissions import mode_runtime
    from test_deliverables import save_plan, read_plan
    from test_work_records import body
    context, _ = await mode_runtime(setup, 'full', '把需求确认和接口联调这两项加入我的工作，各自保留完整方案')
    runtime = SimpleNamespace(context=context)
    context.intent_model = Judge(False, failure_kind='missing_info')
    # Invoke the actual tool signature: its omitted options include copy_index=1.
    failed = json.loads(await execute_business_action.coroutine(runtime=runtime, step=2,
        action='create_work', changes={'title': '联调方案', 'body': body('对照接口完成联调')}))
    assert failed['state'] == 'clarification' and failed['taskItemId']
    context.intent_model = Judge()
    first = json.loads(await execute_business_action.coroutine(runtime=runtime, step=1,
        action='create_work', changes={'title': '需求确认', 'body': body('确认需求与范围')}))
    assert first['state'] == 'succeeded'
    async with context.sessions() as db:
        stored = await db.get(Job, context.job_id)
        assert stored.result['operationFeedback']
    plan = await save_plan(context, title='实施计划', body='两项计划',
        items=[{'title': '需求确认', 'body': '确认需求与范围'}, {'title': '接口联调', 'body': '对照接口完成联调'}])
    await read_plan(context, plan['id'])
    corrected = json.loads(await execute_business_action.coroutine(runtime=runtime, step=2,
        action='create_work', changes={'title': '接口联调', 'body': body('对照接口完成联调，并记录验收结果')},
        deliverable_id=plan['id'], deliverable_revision=1, item_id=plan['items'][1]['id'], task_item_id=failed['taskItemId']))
    assert corrected['state'] == 'succeeded' and corrected['taskItemId'] == failed['taskItemId'], corrected
    checked = context.intent_model.inputs[-1]
    assert checked['recoveringItem']['id'] == failed['taskItemId']
    assert checked['recoveringItem']['attemptedOperation']['changes']['title'] == '联调方案'
    assert checked['proposedOperation']['deliverableSelection']['items'][0]['id'] == plan['items'][1]['id']
    async with context.sessions() as db:
        stored = await db.get(Job, context.job_id)
        assert not stored.result['operationFeedback']
        stored.state = 'succeeded'
        outcome = derive(stored, [first, corrected])
        assert outcome['state'] == 'completed' and not outcome['remaining'] and outcome['nextAction'] == 'none'
    works = (await setup[3]['employee'].get('/api/v1/work-items')).json()['items']
    assert {item['id'] for item in works} == {first['objectId'], corrected['objectId']}


@pytest.mark.asyncio
async def test_failed_item_reference_cannot_be_reassigned_to_another_source(setup):
    from app.agent.tools.actions import execute_business_action
    from app.tasks.models import Job
    from test_business_actions import Judge
    from test_execution_permissions import mode_runtime
    from test_deliverables import save_plan, read_plan
    from test_work_records import body
    context, _ = await mode_runtime(setup, 'full', '把计划的两项加入工作')
    runtime = SimpleNamespace(context=context)
    plan = await save_plan(context, title='同名的两项', body='',
        items=[{'title': '准备', 'body': '核对需求'}, {'title': '准备', 'body': '配置环境'}])
    await read_plan(context, plan['id'])
    context.intent_model = Judge(False)
    arguments = {'runtime': runtime, 'step': 1, 'action': 'create_work', 'deliverable_id': plan['id'],
                 'deliverable_revision': 1, 'item_id': plan['items'][0]['id'], 'changes': {'title': '准备', 'body': body('核对需求')}}
    failed = json.loads(await execute_business_action.coroutine(**arguments))
    assert failed['taskItemId']
    context.intent_model = Judge()
    stolen = json.loads(await execute_business_action.coroutine(**{**arguments,
        'item_id': plan['items'][1]['id'], 'changes': {'title': '准备', 'body': body('配置环境')}, 'task_item_id': failed['taskItemId']}))
    assert stolen['state'] == 'failed' and not stolen.get('taskItemId'), stolen
    assert (await setup[3]['employee'].get('/api/v1/work-items')).json()['items'] == []
    async with context.sessions() as db:
        stored = await db.get(Job, context.job_id)
        assert any(row.get('taskItemId') == failed['taskItemId'] and row['category'] in ('invalid_arguments', 'missing_info')
                   for row in stored.result['toolOutcomes'])
