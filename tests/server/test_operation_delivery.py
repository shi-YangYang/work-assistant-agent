"""Durable operation status is independent of complete, possibly wrong prose."""
from types import SimpleNamespace
import pytest
from app.tasks.feedback.outcomes import derive, record


def task():
    return SimpleNamespace(result={}, state='succeeded', error='')


@pytest.mark.parametrize('category', ['invalid_arguments', 'permission_denied', 'conflict', 'transient_failure'])
def test_unrecoverable_tool_errors_do_not_request_user_authorization(category):
    job = task()
    record(job, 'update_work', {'target_id': 'work', 'step': 1, 'changes': {'status': 'done'}},
           {'state': 'failed', 'category': category, 'message': '本项未执行'})
    result = derive(job)
    assert result['state'] == 'blocked' and result['nextAction'] == 'none'


def test_one_success_does_not_clear_other_atomic_failure():
    job = task()
    args = {'target_id': 'work', 'step': 1}
    record(job, 'update_work', {**args, 'changes': {'body': {}}}, {'state': 'failed', 'category': 'invalid_arguments'})
    record(job, 'update_work', {**args, 'changes': {'status': 'done'}}, {'state': 'succeeded', 'id': 'one'})
    result = derive(job, [{'state': 'succeeded', 'label': '修改状态'}])
    assert result['state'] == 'partial' and result['remaining']
    record(job, 'update_work', {**args, 'changes': {'body': {'new': True}}}, {'state': 'succeeded', 'id': 'two'})
    assert derive(job, [{'state': 'succeeded', 'label': '修改正文'}])['state'] == 'completed'


def test_real_missing_input_and_async_work_keep_their_distinct_states():
    job = task()
    record(job, 'delete_work', {'target_id': '', 'step': 1}, {'state': 'clarification', 'category': 'missing_info'})
    assert derive(job)['state'] == 'needs_input'
    fresh = task()
    assert derive(fresh, [{'state': 'running', 'label': '生成报告'}])['state'] == 'processing'
    assert derive(fresh, [{'state': 'pending', 'label': '删除工作'}])['state'] == 'needs_confirmation'
