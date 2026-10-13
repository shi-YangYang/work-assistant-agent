"""Report waits are owned by exact receipts; unrelated requirements survive."""
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.tasks.feedback.report_waits import normalize


WAIT = '本周周报草稿生成仍在服务器处理中，暂未拿到保存回执'
LOW_WAIT = '本周周报草稿仍在生成处理中，尚未确认保存完成'
HIGH_WAIT = '周报草稿的生成任务仍在服务器排队处理中，尚未能确认已保存，稍后可在“我的报告”查看结果'
RESULT_WAIT = '保存周报草稿后告知用户结果'
REQUEST = '根据已有工作在我的报告里创建并保存本周周报草稿，不提交。请完成保存后告诉我结果。'
CLOCK = '当前请求时间：2026-10-14T02:09:20+08:00（周三）；公司时区：Asia/Shanghai。'


def fixture():
    task = {'state': 'blocked', 'remaining': [WAIT]}
    item = {'id': 'item', 'receiptId': 'receipt', 'attemptedOperation': {
        'action': 'generate_report', 'kind': 'weekly', 'date': '2026-10-12', 'submitAfter': False}}
    job = SimpleNamespace(target_id='message', result={'taskItems': [item]})
    cards = [{'id': 'receipt', 'messageId': 'message', 'taskItemId': 'item', 'action': 'generate_report',
              'state': 'running', 'title': '2026-10-12 周报', 'objectId': 'report',
              'job': {'kind': 'report', 'targetId': 'report', 'state': 'queued'}}]
    return job, cards, task


@pytest.mark.parametrize('state', ['queued', 'running', 'succeeded', 'failed', 'awaiting_retry', 'cancelled'])
def test_exact_wait_delegates_to_real_card_without_mutating_it(state):
    job, cards, task = fixture()
    cards[0]['job']['state'] = state
    original = deepcopy((job.result, cards, task))
    assert normalize(job, cards, task, clock=CLOCK) == {'state': 'completed', 'remaining': []}
    assert (job.result, cards, task) == original


@pytest.mark.parametrize('remaining', [
    '上周周报草稿生成仍在服务器处理中', '2026-10-05 周报生成中', '本周日报生成中',
    '周报生成中', '本周周报尚未提交', '本周周报缺少客户资料',
    WAIT + '，还需创建客户回访工作', '选择需要生成周报的工作',
])
def test_other_period_submission_missing_input_and_mixed_prose_are_not_discarded(remaining):
    job, cards, task = fixture()
    task['remaining'] = [remaining]
    assert normalize(job, cards, task, clock=CLOCK) == task


@pytest.mark.parametrize('change', ['submit', 'unknown_submit', 'date', 'kind', 'receipt', 'message', 'target', 'child_kind', 'unavailable', 'ambiguous', 'clock'])
def test_wait_requires_unambiguous_same_message_report_identity(change):
    job, cards, task = fixture()
    item = job.result['taskItems'][0]
    if change == 'submit':
        item['attemptedOperation']['submitAfter'] = True
    elif change == 'unknown_submit':
        del item['attemptedOperation']['submitAfter']
    elif change in ('date', 'kind'):
        item['attemptedOperation'][change] = '2026-10-05' if change == 'date' else 'daily'
    elif change == 'receipt':
        item['receiptId'] = 'another'
    elif change == 'message':
        cards[0]['messageId'] = 'another'
    elif change == 'target':
        cards[0]['job']['targetId'] = 'another'
    elif change == 'child_kind':
        cards[0]['job']['kind'] = 'assistant'
    elif change == 'unavailable':
        cards[0]['state'] = 'unavailable'
    elif change == 'ambiguous':
        job.result['taskItems'].append({**deepcopy(item), 'id': 'item2', 'receiptId': 'receipt2'})
        cards.append({**deepcopy(cards[0]), 'id': 'receipt2', 'taskItemId': 'item2'})
    assert normalize(job, cards, task, clock='' if change == 'clock' else CLOCK) == task


@pytest.mark.parametrize('source', ['intentTaskInterpretation', 'explicitTaskContext', 'budget', 'tool'])
def test_server_observed_or_authorization_requirements_cannot_be_removed(source):
    job, cards, task = fixture()
    if source == 'budget':
        job.result['nodeExecution'] = {'budgetBlockedTools': [WAIT]}
    elif source == 'tool':
        job.result['toolOutcomes'] = [{'category': 'permission_denied', 'message': WAIT}]
    else:
        job.result[source] = {'state': 'needs_input', 'remaining': [WAIT]}
    assert normalize(job, cards, task, clock=CLOCK) == task


def test_other_remaining_is_retained_when_one_report_wait_is_resolved():
    job, cards, task = fixture()
    task['remaining'].append('另一个工作尚未保存')
    assert normalize(job, cards, task, clock=CLOCK) == {'state': 'blocked', 'remaining': ['另一个工作尚未保存']}


def authorize_period(job):
    job.result['taskItems'][0]['userSource'] = {'messageId': 'message', 'userText': REQUEST}


@pytest.mark.parametrize('remaining', [[WAIT], [LOW_WAIT], [RESULT_WAIT, HIGH_WAIT]])
def test_observed_remaining_forms_delegate_only_the_exact_report(remaining):
    job, cards, task = fixture()
    authorize_period(job)
    job.result['intentTaskInterpretation'] = {'state': 'needs_confirmation', 'remaining': [RESULT_WAIT]}
    task['remaining'] = remaining
    assert normalize(job, cards, task, clock=CLOCK) == {'state': 'completed', 'remaining': []}


@pytest.mark.parametrize('remaining', [
    HIGH_WAIT + '，还需创建客户回访工作', RESULT_WAIT + '并发送邮件',
    '保存上周周报草稿后告知用户结果', '保存日报草稿后告知用户结果',
    '提交周报后告知用户结果', '保存周报草稿并提交后告知用户结果',
    '周报草稿缺少资料，尚未能确认已保存', '周报草稿生成失败，稍后可在“我的报告”查看结果',
    '周报草稿正在处理中，缺少生成授权',
])
def test_bound_report_cannot_fulfill_other_actions_or_failed_preconditions(remaining):
    job, cards, task = fixture()
    authorize_period(job)
    task['remaining'] = [remaining]
    assert normalize(job, cards, task, clock=CLOCK) == task


@pytest.mark.parametrize('boundary', ['missing_source', 'old_message', 'different_period', 'two_periods', 'continued_period', 'missing_clock'])
def test_unqualified_report_requires_current_source_and_unambiguous_authorized_period(boundary):
    job, cards, task = fixture()
    authorize_period(job)
    task['remaining'] = [HIGH_WAIT, RESULT_WAIT]
    source = job.result['taskItems'][0]['userSource']
    if boundary == 'missing_source':
        source.clear()
    elif boundary == 'old_message':
        source['messageId'] = 'old-message'
    elif boundary == 'different_period':
        source['userText'] = '生成2026-10-05 周报草稿'
    elif boundary in ('two_periods', 'continued_period'):
        source['userText'] = '保存2026-10-05 周报和2026-10-12 周报草稿'
        second = deepcopy(job.result['taskItems'][0])
        second.update(id='second-item', receiptId='second-receipt')
        second['attemptedOperation']['date'] = '2026-10-05'
        if boundary == 'continued_period':
            second['userSource']['messageId'] = 'old-message'
        job.result['taskItems'].append(second)
        card = deepcopy(cards[0])
        card.update(id='second-receipt', taskItemId='second-item', title='2026-10-05 周报')
        cards.append(card)
    assert normalize(job, cards, task, clock='' if boundary == 'missing_clock' else CLOCK) == task


@pytest.mark.parametrize('source', ['intentTaskInterpretation', 'explicitTaskContext', 'budget', 'tool'])
def test_even_bound_result_notification_preserves_real_input_permission_and_budget_failures(source):
    job, cards, task = fixture()
    authorize_period(job)
    task['remaining'] = [RESULT_WAIT]
    if source == 'budget':
        job.result['nodeExecution'] = {'budgetBlockedTools': [RESULT_WAIT]}
    elif source == 'tool':
        job.result['toolOutcomes'] = [{'category': 'permission_denied', 'message': RESULT_WAIT}]
    else:
        job.result[source] = {'state': 'needs_input', 'remaining': [RESULT_WAIT]}
    assert normalize(job, cards, task, clock=CLOCK) == task


@pytest.mark.parametrize('state', ['processing', 'needs_confirmation'])
def test_authorized_result_notice_is_card_owned_without_a_model_wait_header(state):
    job, cards, task = fixture()
    authorize_period(job)
    task = {'state': state, 'remaining': [RESULT_WAIT]}
    job.result['intentTaskInterpretation'] = deepcopy(task)
    assert normalize(job, cards, task, clock=CLOCK) == {'state': 'completed', 'remaining': []}


@pytest.mark.asyncio
@pytest.mark.parametrize('trace', ['v1_high', 'v2_low', 'v2_high'])
@pytest.mark.parametrize('terminal', ['succeeded', 'failed', 'cancelled', 'other_remaining'])
async def test_original_high_trace_public_api_follows_real_report_without_extra_model_call(setup, monkeypatch, terminal, trace):
    from sqlalchemy import func, select
    from app.agent.completion.delivery import delivery_for
    from app.modules.reports.models import Report
    from app.tasks.models import Job
    from app.tasks.processing.handlers import process_job
    from app.tasks.runtime.queue import claim
    from _support.agent.business_actions import ReplyJudge, create, execute, run_reply
    from _support.work.report_reliability import ReportModel

    settings, sessions, users, clients = setup
    await create(clients['employee'], title='资料核对-R01', summary='已核对5份客户资料，尚余2份', status='in_progress')
    answer = '周报草稿已发起生成，不会提交。'
    wait = {'v1_high': WAIT, 'v2_low': LOW_WAIT, 'v2_high': HIGH_WAIT}[trace]
    remainder = [wait] + (['另一个工作尚未保存'] if terminal == 'other_remaining' else [])
    async def enqueue(context):
        result = await execute(context, step=1, action='generate_report', report_kind='weekly', report_date='2026-10-12')
        assert result['state'] == 'running'
        assert len(context.intent_model.inputs) == 1
        if trace == 'v2_high':
            async with sessions.begin() as db:
                job = await db.get(Job, context.job_id)
                job.result = {**job.result, 'intentTaskInterpretation': {
                    'state': 'needs_confirmation', 'remaining': [RESULT_WAIT]}}
    async def graph(context, *args, **kwargs):
        context.request_clock = CLOCK
        raw = '<!--noria:' + json.dumps({'remaining': remainder}, ensure_ascii=False) + '-->\n' + answer
        context.delivery = (await delivery_for(context, raw)).model_dump()
        return answer
    monkeypatch.setattr('app.tasks.processing.handlers.invoke_harness', graph)
    data = await run_reply(setup, REQUEST, answer,
                           ReplyJudge([], fail=True), before=enqueue)
    assert len(data['actions']) == 1
    assert data['job']['taskOutcome']['state'] == 'processing'
    assert wait not in data['reply'] and RESULT_WAIT not in data['reply']
    assert data['job']['incompleteTask'] is (terminal == 'other_remaining')
    child = data['actions'][0]['job']['id']
    if terminal in ('succeeded', 'other_remaining'):
        generation = await claim(sessions, users['employee'].id)
        assert generation.id == child
        model = ReportModel(json.dumps({'completed': '已核对5份客户资料', 'ongoing': '尚余2份', 'blockers': '', 'next': '核对剩余资料'}, ensure_ascii=False))
        await process_job(generation, sessions, settings, None, model=model)
        assert model.calls == 1
    else:
        async with sessions.begin() as db:
            job = await db.get(Job, child)
            job.state, job.phase = terminal, terminal
            job.error = '受控报告失败' if terminal == 'failed' else ''
    latest = (await clients['employee'].get('/api/v1/messages/' + data['id'])).json()
    expected = {'succeeded': 'completed', 'other_remaining': 'partial', 'failed': 'blocked', 'cancelled': 'cancelled'}[terminal]
    assert latest['job']['taskOutcome']['state'] == expected
    assert wait not in latest['job']['taskOutcome']['remaining']
    assert RESULT_WAIT not in latest['job']['taskOutcome']['remaining']
    assert wait not in latest['reply'] and RESULT_WAIT not in latest['reply'] and answer in latest['reply']
    if terminal == 'other_remaining':
        assert '另一个工作尚未保存' in latest['job']['taskOutcome']['remaining']
    if terminal == 'succeeded':
        assert latest['job']['taskOutcome']['remaining'] == []
        assert '本次请求仍有操作未完成' not in latest['reply']
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Report).where(Report.owner_id == users['employee'].id)) == 1
        report = await db.get(Report, data['actions'][0]['objectId'])
        assert report.published_revision == 0
