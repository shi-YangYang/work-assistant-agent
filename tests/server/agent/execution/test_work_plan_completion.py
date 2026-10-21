"""Atomic work writes may finish independently; a receipt cannot finish their plan."""
import copy
from types import SimpleNamespace

import pytest

from app.agent.actions.operations import execute
from app.agent.completion.completion import receipt_completion
from app.agent.completion.delivery import Delivery, assess
from app.tasks.feedback.outcomes import derive
from app.tasks.feedback.work_requirements import remember, remaining
from app.tasks.models import Job
from _support.agent.assistant_execution import ReceiptJudge, returned
from _support.agent.business_actions import create, read_work, runtime
from _support.work.work_change_plan import PlanJudge
from _support.work.work_records import body
from _support.work.work_plan_completion import card, job_value


def requirements(job, fields=('body', 'nextStep'), *, scope='input', revision=1, prior=()):
    remember(job, scope=scope, target='work', revision=revision, title='任务', fields=fields,
             previous_receipts=list(prior))


@pytest.mark.parametrize('bad', [
    {'objectId': 'other'}, {'messageId': 'previous'}, {'objectRevision': 0},
    {'state': 'failed'}, {'state': 'conflict'}, {'state': 'unavailable'}, {'state': 'running'},
    {'state': 'pending'}, {'id': 'old'}, {'action': 'create_work'},
])
def test_only_current_target_version_and_successful_new_receipts_cover_fields(bad):
    job = job_value()
    requirements(job, prior=['old'])
    assert remaining(job, [card(**bad)])
    assert derive(job, [card(**bad)])['state'] != 'completed'
    assert not remaining(job, [card()])


def test_plan_corrections_replace_fields_but_retained_fields_keep_first_baseline():
    job = job_value()
    requirements(job)
    saved = card(changedFields=['nextStep'])
    requirements(job, revision=2, prior=['receipt'])
    assert remaining(job, [saved])[0]['fields'] == ['body']
    requirements(job, fields=['nextStep'], revision=2, prior=['receipt'])
    assert remaining(job, [saved]) == []  # The new independent plan withdrew body.
    requirements(job, fields=['body'], revision=1)
    assert remaining(job, [saved]) == []  # An older concurrent extraction cannot undo it.
    requirements(job, scope='corrected-input', fields=['nextStep'], revision=2, prior=['receipt'])
    assert remaining(job, [saved])[0]['fields'] == ['nextStep']
    assert remaining(copy.deepcopy(job), [card(id='new', objectRevision=2, changedFields=['nextStep'])]) == []


def test_valid_pending_card_is_accounted_for_without_claiming_success():
    job = job_value()
    requirements(job, fields=['body'])
    job.result['taskItems'] = [{'id': 'item', 'targetId': 'work'}]
    pending = card(state='pending', taskItemId='item', objectId=None, objectRevision=None,
                   canConfirm=True, preview={'revision': 1, 'changes': {'bodyEdits': []}})
    assert remaining(job, [pending])[0]['fields'] == ['body']
    assert remaining(job, [pending], include_pending=True) == []
    outcome = derive(job, [pending])
    assert outcome['state'] == 'needs_confirmation' and outcome['completed'] == []
    assert outcome['nextAction'] == 'confirm'
    assert remaining(job, [{**pending, 'canConfirm': False}], include_pending=True)


@pytest.mark.asyncio
async def test_partial_atomic_success_continues_and_final_state_preserves_full_prose(setup):
    client = setup[3]['employee']
    work = await create(client, '客户反馈', body=body('整理客户问题'))
    text = '补充正文：收到三份反馈，并另记进展：已收集反馈，下一步归类。不要改变状态。'
    context, _ = await runtime(setup, text)
    context.work_change_model = PlanJudge({'body': ('set', '补充正文：收到三份反馈', None),
        'update': ('set', '另记进展：已收集反馈', None), 'nextStep': ('set', '下一步归类', None)})
    context.intent_model = ReceiptJudge(required_fields=['body', 'update', 'nextStep'], requested_changes=[
        {'field': 'body', 'kind': 'content', 'quote': '补充正文：收到三份反馈'},
        {'field': 'update', 'kind': 'progress', 'quote': '另记进展：已收集反馈'},
        {'field': 'nextStep', 'kind': 'next_action', 'quote': '下一步归类'}])
    await read_work(context, work['id'])
    first = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=1,
                          changes={'update': {'action': 'create', 'text': '已收集反馈'}, 'nextStep': '归类'})
    assert first['state'] == 'succeeded' and first['remainingChanges'][0]['fields'] == ['body']
    assert not await receipt_completion(context, returned(first))
    context.delivery = Delivery(answer='已经全部保存。这是额外建议：按主题归类。',
                                task={}, verification_requested=False,
                                business_requested=True, operation_ids=[first['id']]).model_dump()
    review = await assess(context, context.delivery['answer'])
    assert review.text == context.delivery['answer'] and not review.needs_action
    assert review.task['state'] == 'blocked' and '工作正文' in review.task['remaining'][0]
    async with context.sessions() as db:
        live = await db.get(Job, context.job_id)
        live.state = 'succeeded'
        outcome = derive(live, [first], interpretation=review.task)
        assert outcome['state'] == 'partial' and outcome['nextAction'] == 'none'
    # Recovering the tool result from a fresh context must preserve the missing group.
    resumed = copy.copy(context)
    repeated = await execute(resumed, step=1, action='update_work', target_id=work['id'], expected_revision=1,
                             changes={'update': {'action': 'create', 'text': '已收集反馈'}, 'nextStep': '归类'})
    assert repeated['id'] == first['id'] and repeated['remainingChanges'] == first['remainingChanges']
    second = await execute(resumed, step=2, action='update_work', target_id=work['id'], expected_revision=2,
                           changes={'bodyEdits': [{'action': 'append', 'blocks': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': '收到三份反馈'}]}]}]})
    assert second['state'] == 'succeeded' and 'remainingChanges' not in second
    context.delivery['operation_ids'].append(second['id'])
    final = await assess(context, context.delivery['answer'])
    assert final.task['state'] == 'completed' and final.task['remaining'] == []
    after = (await client.get('/api/v1/work-items/' + work['id'])).json()
    assert after['revision'] == 3 and after['status'] == 'in_progress'
    assert after['bodyText'] == '整理客户问题\n收到三份反馈' and after['nextStep'] == '归类'
    updates = (await client.get('/api/v1/work-items/' + work['id'] + '/updates')).json()['items']
    assert len(updates) == 1
    assert len(context.intent_model.inputs) == 2 and len(context.work_change_model.inputs) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('pending', [False, True])
async def test_complete_single_operation_keeps_fast_receipt_with_preserved_equal_fields(setup, pending):
    work = await create(setup[3]['employee'], '简单修改', dueDate='2026-10-12')
    context, _ = await runtime(setup, '下一步归类，截止日期仍为2026-10-12，保留状态。')
    context.work_change_model = PlanJudge({'nextStep': ('set', '下一步归类', None),
        'dueDate': ('set', '截止日期仍为2026-10-12', '2026-10-12')})
    context.intent_model = ReceiptJudge(required_fields=['nextStep', 'dueDate'], requested_changes=[
        {'field': 'nextStep', 'kind': 'next_action', 'quote': '下一步归类'},
        {'field': 'dueDate', 'kind': 'deadline', 'quote': '截止日期仍为2026-10-12'}])
    if pending:
        from app.modules.members.models import Member
        async with context.sessions.begin() as db:
            member = await db.get(Member, context.owner_id)
            member.execution_mode = 'ask'
    await read_work(context, work['id'])
    result = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=1,
                           changes={'nextStep': '归类'})
    assert result['state'] == ('pending' if pending else 'succeeded')
    assert 'remainingChanges' not in result and await receipt_completion(context, returned(result))
    assert len(context.intent_model.inputs) == len(context.work_change_model.inputs) == 1
    if pending:
        async with context.sessions.begin() as db:
            live = await db.get(Job, context.job_id)
            live.state, live.phase, live.lease_until = 'awaiting_input', 'awaiting_confirmation', None
            live.result = {**live.result, 'taskInterpretation': {'state': 'needs_confirmation', 'remaining': []}}
        confirmed = await setup[3]['employee'].post('/api/v1/business-actions/' + result['id'] + '/confirm',
                                                  json={'expectedRevision': result['revision']})
        assert confirmed.status_code == 200, confirmed.text
        feedback = (await setup[3]['employee'].get('/api/v1/jobs/' + context.job_id + '/feedback')).json()
        assert feedback['taskOutcome']['state'] == 'completed', feedback
        assert feedback['taskOutcome']['remaining'] == []


@pytest.mark.asyncio
async def test_input_scope_reset_discards_old_requirements_but_worker_resume_keeps_them(setup):
    from app.tasks.nodes.node_execution import initialize
    context, _ = await runtime(setup, '保存正文')
    context.node_retry = True
    await initialize(context, 'original-input')
    async with context.sessions.begin() as db:
        live = await db.get(Job, context.job_id)
        remember(live, scope=context.node_scope, target='work', revision=1, title='任务', fields=['body'], previous_receipts=[])
        remember(live, scope=context.node_scope, target='candidate', revision=1, title='尚未选定', fields=['materials'], previous_receipts=[], selected=False)
    await initialize(copy.copy(context), 'original-input')
    async with context.sessions() as db:
        assert (await db.get(Job, context.job_id)).result['workChangeRequirements']['targets']['work']['fields']
        assert (await db.get(Job, context.job_id)).result['workChangeCandidates']['targets']['candidate']['fields']
    await initialize(context, 'changed-input')
    async with context.sessions() as db:
        assert 'workChangeRequirements' not in (await db.get(Job, context.job_id)).result
        assert 'workChangeCandidates' not in (await db.get(Job, context.job_id)).result


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid', ['role', 'target_owner', 'removed_target'])
async def test_confirmation_coverage_revalidates_visibility(setup, invalid):
    from app.modules.operations.models import BusinessAction
    from app.modules.work.models import WorkItem
    from app.tasks.feedback.work_requirements import settled_receipt
    work = await create(setup[3]['employee'], '真实目标')
    context, _ = await runtime(setup, '下一步归类')
    context.intent_model = ReceiptJudge()
    await read_work(context, work['id'])
    result = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=1,
                           changes={'nextStep': '归类'})
    async with context.sessions.begin() as db:
        row = await db.get(BusinessAction, result['id'])
        target = await db.get(WorkItem, work['id'])
        if invalid == 'role':
            row.access = {**row.access, 'role': 'admin'}
        elif invalid == 'target_owner':
            target.owner_id = setup[2]['peer'].id
        else:
            target.deleted = True
        observed = await settled_receipt(db, setup[2]['employee'], row)
        assert observed['state'] == 'unavailable' and not observed.get('changedFields')
