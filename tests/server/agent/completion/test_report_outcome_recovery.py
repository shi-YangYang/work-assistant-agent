"""Same report retries resolve; different intents and authorization remain distinct."""
import json
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from app.agent.actions.operations import execute
from app.db.base import now
from app.modules.reports.models import Report
from app.tasks.feedback.outcomes import derive, record
from app.tasks.models import Job
from app.tasks.processing.handlers import process_job
from app.tasks.runtime.queue import claim
from _support.agent.business_actions import Judge, create, finish, runtime
from _support.work.report_reliability import ReportModel


BASE = {'step': 1, 'report_kind': 'weekly', 'report_date': '2026-10-14'}
FAILURE = {'state': 'failed', 'category': 'permission_denied', 'message': '督办来源必须来自实际读取的工作或报告'}


def task():
    return SimpleNamespace(result={}, state='succeeded', error='')


def test_original_j06_source_corrections_resolve_only_the_report():
    job = task()
    for token in ('work:synthetic-id', 'synthetic-id'):
        record(job, 'generate_report', {**BASE, 'source_tokens': [token]}, FAILURE)
    record(job, 'create_work', {'step': 2, 'changes': {'title': '独立工作'}, 'source_tokens': ['denied']}, FAILURE)
    resolved = record(job, 'generate_report', {**BASE, 'step': 3, 'report_date': '2026-10-12', 'task_item_id': 'verified-report'},
                      {'state': 'running', 'id': 'real-receipt'})
    assert len(resolved) == 3
    assert len(job.result['operationFeedback']) == 1
    assert job.result['operationFeedback'][0]['action'] == 'create_work'
    assert derive(job, [{'state': 'succeeded', 'label': '生成报告'}])['state'] == 'partial'
    report = [row for row in job.result['toolOutcomes'] if row['action'] == 'generate_report']
    assert len(report) == 1 and report[0]['receiptId'] == 'real-receipt'


@pytest.mark.parametrize('different', [
    {'report_kind': 'daily'}, {'report_date': '2026-10-19'}, {'obligation_id': 'another-obligation'},
    {'submit_after': True}, {'target_id': 'another-target'}, {'task_item_id': 'another-intent'},
    {'deliverable_id': 'another-source'},
])
def test_corrected_report_cannot_clear_another_intent_even_with_shared_step(different):
    job = task()
    first = {**BASE, 'task_item_id': 'first-intent', 'source_tokens': ['invalid-source']}
    record(job, 'generate_report', first, FAILURE)
    record(job, 'generate_report', {**first, 'source_tokens': [], **different}, {'state': 'running', 'id': 'other'})
    assert len(job.result['operationFeedback']) == 1
    assert derive(job, [{'state': 'succeeded'}])['state'] == 'partial'


def test_corrected_arguments_without_admitted_result_do_not_resolve_failure():
    job = task()
    record(job, 'generate_report', {**BASE, 'source_tokens': ['invalid-source']}, FAILURE)
    record(job, 'generate_report', BASE, {'state': 'failed', 'category': 'permission_denied', 'message': '无权生成'})
    assert len(job.result['operationFeedback']) == 2
    assert derive(job)['state'] == 'blocked'


def corrected_draft():
    job = task()
    job.target_id = 'current-message'
    arguments = {**BASE, 'task_item_id': 'same-item'}
    record(job, 'generate_report', {**arguments, 'submit_after': True},
           {'state': 'failed', 'category': 'invalid_arguments', 'message': '用户只要草稿，不能提交'})
    job.result['taskItems'] = [{'id': 'same-item', 'action': 'generate_report', 'state': 'running',
        'receiptId': 'draft-receipt', 'userSource': {'messageId': 'current-message'},
        'attemptedOperation': {'action': 'generate_report', 'submitAfter': False}}]
    result = {'id': 'draft-receipt', 'action': 'generate_report', 'state': 'running',
              'messageId': 'current-message', 'objectId': 'report',
              'job': {'kind': 'report', 'targetId': 'report'}}
    return job, arguments, result


def test_same_authorized_draft_correction_resolves_unexecuted_submit_rejection():
    job, arguments, result = corrected_draft()
    resolved = record(job, 'generate_report', arguments, result)
    assert len(resolved) == 2
    assert not job.result['operationFeedback']
    assert len(job.result['toolOutcomes']) == 1


@pytest.mark.parametrize('boundary', [
    'different_item', 'different_period', 'different_kind', 'different_obligation', 'different_target',
    'different_reference', 'missing_binding', 'old_message', 'different_receipt', 'different_child',
    'old_user_source', 'submit_requested', 'unknown_submit', 'permission_denied', 'old_receipt',
    'pending_receipt', 'failed_receipt',
])
def test_draft_correction_keeps_other_failures_and_real_submit_requests(boundary):
    job, arguments, result = corrected_draft()
    bound = job.result['taskItems'][0]
    if boundary.startswith('different_') and boundary not in ('different_receipt', 'different_child'):
        key, value = {'different_item': ('task_item_id', 'another-item'),
            'different_period': ('report_date', '2026-10-19'), 'different_kind': ('report_kind', 'daily'),
            'different_obligation': ('obligation_id', 'another-obligation'),
            'different_target': ('target_id', 'another-target'),
            'different_reference': ('deliverable_id', 'another-source')}[boundary]
        arguments[key] = value
    elif boundary == 'missing_binding':
        job.result['taskItems'] = []
    elif boundary == 'old_message':
        result['messageId'] = 'old-message'
    elif boundary == 'different_receipt':
        bound['receiptId'] = 'another-receipt'
    elif boundary == 'different_child':
        result['job']['targetId'] = 'another-report'
    elif boundary == 'old_user_source':
        bound['userSource']['messageId'] = 'old-message'
    elif boundary == 'submit_requested':
        bound['attemptedOperation']['submitAfter'] = True
    elif boundary == 'unknown_submit':
        del bound['attemptedOperation']['submitAfter']
    elif boundary == 'permission_denied':
        job.result['toolOutcomes'][0]['category'] = 'permission_denied'
    elif boundary == 'old_receipt':
        job.result['toolOutcomes'][0]['receiptId'] = 'prior-pending-submit'
    else:
        result['state'] = 'pending' if boundary == 'pending_receipt' else 'failed'
    record(job, 'generate_report', arguments, result)
    assert job.result['operationFeedback']
    assert any(entry['message'] == '用户只要草稿，不能提交' for entry in job.result['toolOutcomes'])


@pytest.mark.asyncio
async def test_corrected_submit_flag_uses_same_authorized_item_and_only_generates_one_draft(setup):
    settings, sessions, users, clients = setup
    await create(clients['employee'], title='方案', summary='方案初稿已完成', status='done')
    context, sent = await runtime(setup, '根据已有工作起草本周周报草稿，先别提交', allowed=False)
    arguments = {'step': 1, 'action': 'generate_report', 'report_kind': 'weekly',
                 'report_date': now().astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()}
    denied = await execute(context, **arguments, submit_after=True)
    assert denied['state'] == 'failed' and denied['taskItemId']
    context.intent_model = Judge()
    accepted = await execute(context, **arguments, task_item_id=denied['taskItemId'])
    assert accepted['state'] == 'running' and accepted['taskItemId'] == denied['taskItemId']
    assert len(context.intent_model.inputs) == 1  # Uses the existing authorization, no extra model pass.
    async with sessions.begin() as db:
        parent = await db.get(Job, context.job_id)
        assert not parent.result['operationFeedback']
        assert len(parent.result['toolOutcomes']) == 1
        assert len(parent.result['taskItems']) == 1
    await finish(context)
    generation = await claim(sessions, users['employee'].id)
    model = ReportModel(json.dumps({'completed': '方案初稿已完成', 'ongoing': '', 'blockers': '', 'next': ''}, ensure_ascii=False))
    await process_job(generation, sessions, settings, None, model=model)
    actual = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert actual['job']['taskOutcome']['state'] == 'completed'
    assert actual['job']['taskOutcome']['remaining'] == []
    assert len(actual['actions']) == 1 and actual['actions'][0]['state'] == 'succeeded'
    async with sessions() as db:
        report = await db.get(Report, accepted['objectId'])
        assert report.published_revision == 0
        assert await db.scalar(select(func.count()).select_from(Report).where(Report.owner_id == users['employee'].id)) == 1


@pytest.mark.asyncio
async def test_j06_retry_trace_has_one_report_and_completed_public_outcome(setup):
    settings, sessions, users, clients = setup
    await create(clients['employee'], title='方案', summary='方案初稿已完成', status='done')
    context, sent = await runtime(setup, '根据已有工作起草本周周报草稿，下一步写继续核对，先别提交')
    args = {'step': 1, 'action': 'generate_report', 'report_kind': 'weekly',
            'report_date': now().astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()}
    for bad in ({'changes': {'brief': '原始要求'}}, {'changes': {'focus': '进展'}},
                {'source_tokens': ['work:synthetic-id']}, {'source_tokens': ['synthetic-id']}):
        denied = await execute(context, **args, **bad)
        assert denied['state'] == 'failed' and denied['category'] == 'invalid_arguments'
        assert 'changes 与 source_tokens 留空' in denied['message']
    assert context.intent_model.inputs == []
    accepted = await execute(context, **args)
    assert accepted['state'] == 'running'
    assert len(context.intent_model.inputs) == 1
    assert (await execute(context, **args))['id'] == accepted['id']
    assert len(context.intent_model.inputs) == 1  # Durable retry needs no new authorization call.
    async with sessions.begin() as db:
        row = await db.get(Job, context.job_id)
        assert not row.result['operationFeedback']
        row.result = {**row.result, 'taskOutcome': derive(row, [accepted])}
    await finish(context)
    generation = await claim(sessions, users['employee'].id)
    model = ReportModel(json.dumps({'completed': '方案初稿已完成', 'ongoing': '', 'blockers': '', 'next': '继续核对'}, ensure_ascii=False))
    await process_job(generation, sessions, settings, None, model=model)
    message = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert message['job']['taskOutcome']['state'] == 'completed', message
    assert message['job']['taskOutcome']['remaining'] == []
    assert len(message['actions']) == 1 and message['actions'][0]['state'] == 'succeeded'
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Report).where(Report.owner_id == users['employee'].id)) == 1
        report = await db.get(Report, accepted['objectId'])
        assert report.published_revision == 0
    assert model.calls == 1
