"""Plan-rejected proposals expire only after their real requested work is saved."""
import copy
import json
from types import SimpleNamespace

import pytest

from app.agent.actions.operations import execute
from app.agent.actions.task_items import reference_error
from app.tasks.feedback.outcomes import derive, record, reconcile
from app.tasks.feedback.work_requirements import remember
from app.tasks.models import Job
from test_assistant_execution import ReceiptJudge
from test_business_actions import create, read_work, runtime
from test_work_change_plan import PlanJudge
from test_work_plan_completion import card, job_value
from test_work_records import body


def rejected(fields=('body', 'nextStep')):
    job = job_value()
    remember(job, scope='input-source', target='work', revision=1, title='任务', fields=fields,
             previous_receipts=['old'], definitions={name: 'original-user-' + name for name in fields})
    record(job, 'update_work', {'step': 1, 'target_id': 'work', 'expected_revision': 1,
                              'changes': {'update': {'action': 'create', 'text': '错误位置'}}},
           {'state': 'failed', 'category': 'invalid_arguments', 'message': '进展未请求，尚未保存正文',
            'fieldIssues': [{'field': 'update', 'code': 'not_requested'}]})
    assert job.result['toolOutcomes'][0]['planRejection']
    return job


def test_multigroup_plan_rejection_needs_all_actual_receipts():
    job = rejected()
    first = card(changedFields=['bodyEdits'])
    reconcile(job, [first])
    assert job.result['operationFeedback'] and derive(job, [first])['state'] == 'partial'
    second = card(id='second', changedFields=['nextStep'], objectRevision=3)
    reconcile(job, [first, second])
    assert not job.result['operationFeedback'] and derive(job, [first, second])['state'] == 'completed'


@pytest.mark.parametrize('changed', [
    {'objectId': 'other'}, {'messageId': 'old-input'}, {'objectRevision': 0}, {'id': 'old'},
    {'state': 'pending', 'canConfirm': True, 'preview': {'revision': 1, 'changes': {'body': {}, 'nextStep': '确认'}}},
    {'state': 'failed'}, {'state': 'unavailable'}, {'changedFields': ['bodyEdits']},
])
def test_plan_rejection_ignores_pending_partial_old_and_unrelated_receipts(changed):
    job = rejected()
    reconcile(job, [card(**changed)])
    assert job.result['operationFeedback']
    reconcile(job, [card()])
    assert not job.result['operationFeedback']


@pytest.mark.parametrize('changed', ['scope', 'message', 'source', 'plan', 'missing_plan'])
def test_other_inputs_sources_and_plans_cannot_clear_old_rejection(changed):
    job = rejected()
    state = copy.deepcopy(job.result['workChangeRequirements'])
    if changed == 'scope':
        state['scope'] = 'another-input'
    elif changed == 'message':
        job.target_id = 'new-message'
    elif changed == 'source':
        state['targets']['work']['definitions']['body'] = 'another-user-quote'
    elif changed == 'plan':
        state['targets']['work']['definitions']['update'] = 'new-plan-progress'
    else:
        state['targets'] = {}
    job.result['workChangeRequirements'] = state
    reconcile(job, [card(messageId=job.target_id)])
    assert job.result['operationFeedback']


def test_withdrawn_requirements_need_original_completion_and_no_other_failure_is_cleared():
    job = rejected()
    record(job, 'update_work', {'step': 2, 'target_id': 'work', 'task_item_id': 'real-blocked-item',
                              'changes': {'dueDate': '2026-10-12'}},
           {'state': 'failed', 'category': 'permission_denied', 'message': '真实日期修改失败'})
    remember(job, scope='input-source', target='work', revision=2, title='任务', fields=['nextStep'],
             previous_receipts=['body'], definitions={'nextStep': 'original-user-nextStep'})
    reconcile(job, [card(changedFields=['nextStep'])])
    assert len(job.result['operationFeedback']) == 2
    reconcile(job, [card(), card(id='body', changedFields=['bodyEdits'])])
    assert [item['message'] for item in job.result['operationFeedback']] == ['真实日期修改失败']


@pytest.mark.parametrize('same_source', [False, True])
def test_completed_field_omission_keeps_receipt_source_attribution(same_source):
    job = rejected(fields=('body',))
    remember(job, scope='input-source', target='work', revision=1, title='任务', fields=['body'],
             previous_receipts=['old'], definitions={'body': 'original-user-body' if same_source else 'source-B'})
    saved = card(id='receipt-B', changedFields=['bodyEdits'])
    if not same_source:
        reconcile(job, [saved])
    assert job.result['operationFeedback']
    # The next extraction omits the saved field. A reload must retain the
    # original source boundary even though only the same receipt is presented.
    remember(job, scope='input-source', target='work', revision=2, title='任务', fields=[],
             previous_receipts=['old', 'receipt-B'], definitions={})
    job.result = json.loads(json.dumps(job.result))
    reconcile(job, [saved])
    assert bool(job.result['operationFeedback']) is not same_source


def test_old_failure_without_independent_plan_metadata_is_not_backfilled():
    job = rejected()
    del job.result['toolOutcomes'][0]['planRejection']
    reconcile(job, [card()])
    assert job.result['operationFeedback']


@pytest.mark.parametrize('changed', [
    {'task_item_id': 'different-item'},
    {'changes': {'update': {'action': 'delete', 'id': 'entry'}}},
    {'changes': {'update': {'action': 'edit', 'id': 'other', 'text': '修改'}}},
])
def test_known_items_and_progress_suboperations_do_not_resolve_each_other(changed):
    job = job_value()
    arguments = {'step': 1, 'target_id': 'work', 'task_item_id': 'edit-item',
                 'changes': {'update': {'action': 'edit', 'id': 'entry', 'text': '修改'}}}
    record(job, 'update_work', arguments, {'state': 'failed', 'category': 'invalid_arguments', 'message': '未能更正'})
    record(job, 'update_work', {**arguments, **changed}, {'state': 'succeeded', 'id': 'other'})
    assert job.result['operationFeedback'][0]['message'] == '未能更正'
    record(job, 'update_work', arguments, {'state': 'succeeded', 'id': 'actual'})
    assert not job.result['operationFeedback']


def test_removing_forbidden_progress_uses_field_root_but_keeps_suboperation_identity():
    job = job_value()
    record(job, 'update_work', {'step': 1, 'target_id': 'work',
                              'changes': {'body': {}, 'update': {'action': 'create', 'text': '多余'}}},
           {'state': 'failed', 'category': 'invalid_arguments',
            'fieldIssues': [{'field': 'update', 'code': 'not_requested'}]})
    record(job, 'update_work', {'step': 2, 'target_id': 'work', 'changes': {'bodyEdits': []}},
           {'state': 'succeeded', 'id': 'body'})
    assert not job.result['operationFeedback']


@pytest.mark.asyncio
@pytest.mark.parametrize('split', [False, True])
async def test_rejected_progress_then_authorized_body_and_next_step_clear_actual_feedback(setup, split):
    client = setup[3]['employee']
    work = await create(client, '客户走访', body=body('整理三位客户的问题。'))
    context, _ = await runtime(setup, '补充正文：已经收集到三份反馈，下一步归类。不要改变状态。')
    context.work_change_model = PlanJudge({'body': ('set', '补充正文：已经收集到三份反馈', None),
                                         'nextStep': ('set', '下一步归类', None)})
    context.intent_model = ReceiptJudge(required_fields=['body', 'nextStep'], requested_changes=[
        {'field': 'body', 'kind': 'content', 'quote': '补充正文：已经收集到三份反馈'},
        {'field': 'nextStep', 'kind': 'next_action', 'quote': '下一步归类'}])
    await read_work(context, work['id'])
    args = dict(step=1, action='update_work', target_id=work['id'], expected_revision=1)
    failed = await execute(context, **args, changes={'update': {'action': 'create', 'text': '已经收集到三份反馈'}, 'nextStep': '归类'})
    assert failed['state'] == 'failed' and not failed['taskItemId']
    assert not context.intent_model.inputs
    edits = {'bodyEdits': [{'action': 'append', 'blocks': [{'type': 'paragraph', 'content': [
        {'type': 'text', 'text': '已经收集到三份反馈，下一步归类。'}]}]}]}
    cards = []
    if split:
        cards.append(await execute(context, **args, changes={'nextStep': '归类'}))
        async with context.sessions() as db:
            assert (await db.get(Job, context.job_id)).result['operationFeedback']
        args.update(step=2, expected_revision=2)
    else:
        edits['nextStep'] = '归类'
    cards.append(await execute(context, **args, changes=edits))
    assert all(item['state'] == 'succeeded' for item in cards)
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert not job.result['operationFeedback']
        job.state = 'succeeded'
        assert derive(job, cards)['state'] == 'completed'
        item = job.result['taskItems'][-1]
        wrong = {'action': 'update_work', 'targetId': work['id'], 'changes': {'update': {'action': 'create', 'text': '错误替代'}}}
        assert reference_error([item], item['id'], wrong)
    saved = (await client.get('/api/v1/work-items/' + work['id'])).json()
    assert saved['revision'] == (3 if split else 2) and saved['status'] == 'in_progress'
    assert saved['bodyText'] == '整理三位客户的问题。\n已经收集到三份反馈，下一步归类。'
    assert saved['nextStep'] == '归类'
    assert (await client.get('/api/v1/work-items/' + work['id'] + '/updates')).json()['items'] == []


@pytest.mark.asyncio
async def test_compat_suggestion_returns_field_issues_and_corrected_fields_clear_failure(setup):
    from app.agent.tools.work import propose_progress
    work = await create(setup[3]['employee'], '兼容工作', summary='原内容')
    context, _ = await runtime(setup, '只把下一步改为核对，不改说明')
    context.work_change_model = PlanJudge({'nextStep': ('set', '下一步改为核对', None)})
    context.intent_model = ReceiptJudge(required_fields=['nextStep'], requested_changes=[
        {'field': 'nextStep', 'kind': 'next_action', 'quote': '下一步改为核对'}])
    await read_work(context, work['id'])
    rt = SimpleNamespace(context=context)
    failed = json.loads(await propose_progress.coroutine('兼容工作', '多余覆盖', 'in_progress', '', '核对', rt, work_id=work['id']))
    assert failed['fieldIssues'] == [{'field': 'summary', 'code': 'not_requested', 'message': 'summary 未要求修改，保留原值'}]
    async with context.sessions() as db:
        assert (await db.get(Job, context.job_id)).result['toolOutcomes'][0]['category'] == 'invalid_arguments'
    corrected = json.loads(await propose_progress.coroutine('兼容工作', '原内容', 'in_progress', '', '核对', rt, work_id=work['id']))
    assert corrected['state'] == 'succeeded'
    context.suggestion_options.clear()
    context.suggestion_items.clear()
    replay = json.loads(await propose_progress.coroutine('兼容工作', '原内容', 'in_progress', '', '核对', rt, work_id=work['id']))
    assert replay['draftId'] == corrected['draftId']
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert all(item['category'] == 'success' for item in job.result['toolOutcomes'])
    saved = (await setup[3]['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert saved['revision'] == 2 and saved['summary'] == '原内容' and saved['nextStep'] == '核对'
