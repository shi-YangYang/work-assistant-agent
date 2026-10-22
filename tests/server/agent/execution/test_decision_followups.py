"""Committed effects permit related read chains, without reopening all tools."""
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from app.agent.runtime import decision_flow as flow
from app.tasks.context import RunContext


def state():
    context = RunContext('owner', 'company', 'job', 1, None, SimpleNamespace(), source_revision=0)
    job = SimpleNamespace(result={})
    value = flow.current(context, job)
    value['phase'] = 'executing'
    flow.save(job, value)
    return context, job


def begin(context, job, name, key, args=None, metadata=None):
    call = {'name': name, 'id': key, 'args': args or {}}
    batch = AIMessage(id='batch-' + key, content='', tool_calls=[call])
    stopped = flow.begin(context, job, call, batch, metadata or {})
    return {**call, 'decisionId': flow.identity(batch, call)}, stopped


def end(context, job, call, result):
    return flow.end(context, job, call, ToolMessage(name=call['name'], tool_call_id=call['id'], content=json.dumps(result)))


def changed_work(context, job):
    call, stopped = begin(context, job, 'execute_business_action', 'write',
        {'action': 'update_work', 'target_id': 'work', 'expected_revision': 1})
    assert stopped is None
    result = {'state': 'succeeded', 'id': 'operation', 'action': 'update_work',
              'objectType': 'work', 'objectId': 'work', 'objectRevision': 2}
    context.read_versions['work'] = 2
    end(context, job, call, result)
    return call['decisionId'], result


def test_work_change_allows_list_detail_and_paging_until_execution_resumes():
    context, job = state()
    receipt, original = changed_work(context, job)
    names = {'find_work_items', 'get_work_item', 'web_search', 'query_reports', 'read_document', 'save_deliverable'}
    assert flow.available(flow.current(context, job), names) == {'find_work_items', 'get_work_item', 'save_deliverable'}
    metadata = {'after': receipt, 'need': '列出还在进行中的工作并说明下一步'}
    for name, key, args, result in [
        ('find_work_items', 'remaining', {'query': '', 'status': 'in_progress'},
         {'items': [{'id': 'remaining', 'revision': 3}], 'nextCursor': 'next'}),
        ('find_work_items', 'remaining-page', {'query': '', 'status': 'in_progress', 'cursor': 'next'},
         {'items': [{'id': 'another', 'revision': 1}], 'nextCursor': None}),
        ('get_work_item', 'detail', {'work_id': 'remaining'},
         {'id': 'remaining', 'revision': 3, 'nextBodyStart': 20}),
        ('get_work_item', 'detail-page', {'work_id': 'remaining', 'body_start': 20},
         {'id': 'remaining', 'revision': 3, 'nextBodyStart': None}),
    ]:
        call, stopped = begin(context, job, name, key, args, metadata)
        assert stopped is None
        end(context, job, call, result)
        # Persisted scope survives a checkpoint boundary, including discovered IDs.
        job.result = json.loads(json.dumps(job.result))
        assert flow.current(context, job)['phase'] == 'following'
    for name, args in [('web_search', {'query': '顺便查一下'}), ('get_work_item', {'work_id': 'unseen'}),
                       ('query_reports', {}), ('read_document', {'attachment_id': 'unrelated'})]:
        assert begin(context, job, name, 'reject-' + name, args, metadata)[1] is not None
    assert begin(context, job, 'get_work_item', 'no-receipt', {'work_id': 'work'}, {'need': '再确认一下'})[1] is not None
    assert begin(context, job, 'get_work_item', 'fake-receipt', {'work_id': 'work'}, {'need': '读取', 'after': 'fake'})[1] is not None
    # Execution consumes this episode. Replaying its successful result does not
    # create a fresh change or revive the consumed receipt.
    replay, stopped = begin(context, job, 'execute_business_action', 'replay',
        {'action': 'update_work', 'target_id': 'work', 'expected_revision': 1})
    assert stopped is None
    end(context, job, replay, original)
    assert not flow.current(context, job)['calls'][replay['decisionId']].get('changes')
    assert begin(context, job, 'get_work_item', 'old-receipt', {'work_id': 'work'}, metadata)[1] is not None


@pytest.mark.parametrize('name,args,result,read,read_args,unrelated', [
    ('execute_business_action', {'action': 'edit_report', 'target_id': 'report', 'expected_revision': 3},
     {'state': 'succeeded', 'id': 'operation', 'action': 'edit_report', 'objectType': 'report', 'objectId': 'report', 'objectRevision': 4},
     'query_reports', {'report_id': 'report', 'content_start': 1200}, {'report_id': 'other'}),
    ('save_deliverable', {'deliverable_id': 'draft', 'expected_revision': 1},
     {'state': 'succeeded', 'id': 'draft', 'revision': 2},
     'read_deliverable', {'deliverable_id': 'draft', 'offset': 4000}, {'deliverable_id': 'other'}),
    ('run_python', {}, {'state': 'succeeded', 'executionId': 'run', 'delivery': {'id': 'table', 'revision': 1}},
     'inspect_table', {'source': {'input_ref': {'deliverable_id': 'table', 'revision': 1, 'file_id': 'real'}}},
     {'source': {'input_ref': {'attachment_id': 'original'}}}),
    ('generate_image', {}, {'state': 'partial', 'results': [
        {'state': 'succeeded', 'operationId': 'image', 'delivery': {'id': 'picture', 'revision': 1}}, {'state': 'failed'}]},
     'read_deliverable', {'deliverable_id': 'picture'}, {'deliverable_id': 'unknown'}),
])
def test_actual_effect_families_bind_reads_without_authorizing_other_objects(name, args, result, read, read_args, unrelated):
    context, job = state()
    call, stopped = begin(context, job, name, 'write', args)
    assert stopped is None
    end(context, job, call, result)
    metadata = {'after': call['decisionId'], 'need': '按原任务继续读取写入后的结果'}
    assert begin(context, job, read, 'read', read_args, metadata)[1] is None
    assert begin(context, job, read, 'unrelated', unrelated, metadata)[1] is not None
    assert 'web_search' not in flow.available(flow.current(context, job), {'web_search', read})


@pytest.mark.parametrize('name,args,result', [
    ('set_task_context', {}, {'state': 'succeeded', 'id': 'task', 'revision': 1}),
    ('save_memory', {}, {'state': 'succeeded', 'id': 'memory', 'revision': 2}),
    ('run_python', {}, {'state': 'succeeded', 'stdout': 'done'}),
    ('execute_business_action', {'action': 'update_work'}, {'state': 'running', 'id': 'op', 'objectType': 'work', 'objectId': 'work', 'objectRevision': 2}),
    ('save_deliverable', {'expected_revision': 2}, {'state': 'succeeded', 'id': 'draft', 'revision': 2}),
    ('save_deliverable', {}, {'state': 'succeeded', 'id': 'draft'}),
])
def test_control_waiting_unversioned_and_unchanged_results_do_not_reopen_reads(name, args, result):
    context, job = state()
    call, stopped = begin(context, job, name, 'write', args)
    assert stopped is None
    end(context, job, call, result)
    assert not flow.current(context, job)['calls'][call['decisionId']].get('changes')
    assert begin(context, job, 'find_work_items', 'read', {'query': ''},
                 {'after': call['decisionId'], 'need': '再确认'})[1] is not None


def test_deleted_object_opens_its_collection_but_not_the_deleted_detail():
    context, job = state()
    call, _ = begin(context, job, 'execute_business_action', 'delete', {'action': 'delete_work', 'target_id': 'deleted'})
    end(context, job, call, {'state': 'succeeded', 'id': 'operation', 'action': 'delete_work'})
    metadata = {'after': call['decisionId'], 'need': '查看删除后剩余工作'}
    assert begin(context, job, 'find_work_items', 'list', {'query': ''}, metadata)[1] is None
    assert begin(context, job, 'get_work_item', 'detail', {'work_id': 'deleted'}, metadata)[1] is not None


def test_final_answer_consumes_followup_scope_without_changing_waiting_gate():
    context, job = state()
    receipt, _ = changed_work(context, job)
    metadata = {'after': receipt, 'need': '汇总剩余工作'}
    assert begin(context, job, 'find_work_items', 'read', {'query': ''}, metadata)[1] is None
    flow.finish(context, job)
    assert 'find_work_items' not in flow.available(flow.current(context, job), {'find_work_items'})
    assert begin(context, job, 'get_work_item', 'after-answer', {'work_id': 'work'}, metadata)[1] is not None


@pytest.mark.parametrize('expected,allowed', [('1', True), ('', False), (None, False), ({}, False), (True, False)])
def test_committed_result_projection_handles_uncoerced_model_arguments(expected, allowed):
    context, job = state()
    call, _ = begin(context, job, 'save_deliverable', 'write', {'expected_revision': expected})
    returned = end(context, job, call, {'state': 'succeeded', 'id': 'draft', 'revision': 2})
    assert json.loads(returned.content)['state'] == 'succeeded'
    assert bool(flow.current(context, job)['calls'][call['decisionId']].get('changes')) is allowed


@pytest.mark.parametrize('source', [None, 'file', {'input_ref': None}])
def test_malformed_followup_file_reference_never_crashes_admission(source):
    context, job = state()
    call, _ = begin(context, job, 'save_deliverable', 'write')
    end(context, job, call, {'state': 'succeeded', 'id': 'draft', 'revision': 1})
    assert begin(context, job, 'inspect_table', 'read', {'source': source},
                 {'after': call['decisionId'], 'need': '读取生成的表格'})[1] is not None


@pytest.mark.asyncio
async def test_real_work_update_receipt_allows_requested_remaining_query(setup):
    from app.agent.actions.operations import execute
    from app.agent.tools.business.work import find_work_items, get_work_item
    from _support.agent.business_actions import create, runtime
    work = await create(setup[3]['employee'], '已完成项', status='in_progress')
    remaining = await create(setup[3]['employee'], '剩余项', status='in_progress')
    context, _ = await runtime(setup, '把已完成项改为已完成，然后告诉我还剩哪些进行中的工作')
    invoke = SimpleNamespace(context=context)
    value = json.loads(await get_work_item.coroutine(work['id'], invoke))
    job = SimpleNamespace(result={})
    read, _ = begin(context, job, 'get_work_item', 'read', {'work_id': work['id']})
    end(context, job, read, value)
    args = {'step': 1, 'action': 'update_work', 'target_id': work['id'], 'expected_revision': value['revision'], 'changes': {'status': 'done'}}
    write, stopped = begin(context, job, 'execute_business_action', 'write', args, {'ready': [read['decisionId']]})
    assert stopped is None and flow.current(context, job)['phase'] == 'executing'
    receipt = await execute(context, **args)
    assert receipt['state'] == 'succeeded'
    end(context, job, write, receipt)
    query, stopped = begin(context, job, 'find_work_items', 'remaining', {'query': '', 'status': 'in_progress'},
                           {'after': write['decisionId'], 'need': '列出剩余进行中的工作'})
    assert stopped is None
    result = json.loads(await find_work_items.coroutine('', invoke, status='in_progress'))
    end(context, job, query, result)
    assert [item['id'] for item in result['items']] == [remaining['id']]
