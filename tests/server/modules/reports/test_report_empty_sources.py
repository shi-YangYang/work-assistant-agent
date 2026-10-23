"""No-source reports across API, assistant handoff, and legacy job recovery."""
import json
from datetime import timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.agent.tools.business.actions import execute_business_action
from app.db.base import now
from app.modules.model_services.models import ModelUsage
from app.modules.operations.models import BusinessAction
from app.modules.operations.mutations.report_completion import complete_action
from app.modules.reports.models import Report
from app.modules.reports.periods import period
from datetime import date
from app.modules.work.models import WorkItem
from app.tasks.models import Job
from app.tasks.processing.handlers import process_job
from app.tasks.runtime.queue import claim
from _support.agent.business_actions import create
from _support.agent.execution_permissions import mode_runtime
from _support.http.company import keyed
from _support.work.report_reliability import CONTENT, ReportModel, prepared

pytestmark = pytest.mark.asyncio


def today():
    return now().astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()


async def assert_no_generated_report(sessions, actor):
    async with sessions() as db:
        assert not await db.scalar(select(Report.id).where(Report.owner_id == actor.id))
        assert not await db.scalar(select(Job.id).where(Job.owner_id == actor.id, Job.kind == 'report'))
        assert not await db.scalar(select(ModelUsage.id).where(ModelUsage.owner_id == actor.id))


@pytest.mark.parametrize('kind', ['daily', 'weekly'])
async def test_empty_generation_creates_nothing_and_same_request_can_succeed_after_work_added(setup, kind):
    settings, sessions, users, clients = setup
    client, actor = clients['employee'], users['employee']
    request = {'kind': kind, 'date': today()}
    headers = keyed()
    for _ in range(2):
        result = await client.post('/api/v1/reports/generate', json=request, headers=headers)
        assert result.status_code == 422, result.text
        error = result.json()['error']
        assert error['code'] == 'report_sources_empty'
        assert ('周报' if kind == 'weekly' else '日报') in error['message']
        start, end = period(kind, date.fromisoformat(request['date']))
        assert start.isoformat() in error['message'] and end.isoformat() in error['message']
        assert '核对汇报周期' in error['message']
        assert '当前会话' in error['message'] and '正文' in error['message']
    assert not (await client.get('/api/v1/reports', params={'kind': kind})).json()['items']
    await assert_no_generated_report(sessions, actor)

    await create(client, '方案', summary='初稿完成', nextStep='等待确认')
    ready = await client.post('/api/v1/reports/generate', json=request, headers=headers)
    assert ready.status_code == 202, ready.text
    replay = await client.post('/api/v1/reports/generate', json=request, headers=headers)
    assert replay.json() == ready.json()
    model = ReportModel()
    await process_job(await claim(sessions, actor.id), sessions, settings, None, model=model)
    report = (await client.get('/api/v1/reports/' + ready.json()['reportId'])).json()
    assert report['content'] == CONTENT and report['job']['state'] == 'succeeded'
    assert model.calls == 1 and len(model.reviews) == 1


async def test_work_outside_period_is_not_used_and_existing_report_is_unchanged(setup):
    settings, sessions, users, clients = setup
    client, actor = clients['employee'], users['employee']
    report, job, work = await prepared(setup)
    await process_job(await claim(sessions, actor.id), sessions, settings, None, model=ReportModel())
    saved = (await client.get('/api/v1/reports/' + report.id)).json()
    submitted = await client.post('/api/v1/reports/' + report.id + '/submit', json={'expectedRevision': saved['revision']}, headers=keyed())
    assert submitted.status_code == 200, submitted.text

    other_period = (now().astimezone(ZoneInfo('Asia/Shanghai')).date() - timedelta(days=14)).isoformat()
    outside = await client.post('/api/v1/reports/generate', json={'kind': 'weekly', 'date': other_period}, headers=keyed())
    assert outside.status_code == 422 and outside.json()['error']['code'] == 'report_sources_empty'
    async with sessions.begin() as db:
        # Simulate the last source being removed after a report was already saved.
        (await db.get(WorkItem, work.id)).deleted = True
        (await db.get(Report, report.id)).candidate = {'content': {**CONTENT, 'next': '保留候选计划'}, 'sourceIds': []}
    before = (await client.get('/api/v1/reports/' + report.id)).json()
    missing = await client.post('/api/v1/reports/generate', json={'kind': 'daily', 'date': report.period}, headers=keyed())
    assert missing.status_code == 422 and missing.json()['error']['code'] == 'report_sources_empty'
    assert (await client.get('/api/v1/reports/' + report.id)).json() == before
    async with sessions() as db:
        assert list((await db.scalars(select(Report.id).where(Report.owner_id == actor.id))).all()) == [report.id]
        assert list((await db.scalars(select(Job.id).where(Job.owner_id == actor.id, Job.kind == 'report'))).all()) == [job.id]


async def test_assistant_generation_returns_no_source_message_without_blank_report_or_submit(setup):
    context, _ = await mode_runtime(setup, 'full', '生成并提交本周周报')
    args = {'step': 1, 'action': 'generate_report', 'runtime': SimpleNamespace(context=context),
            'report_kind': 'weekly', 'report_date': today(), 'submit_after': True}
    result = json.loads(await execute_business_action.coroutine(**args))
    assert result['state'] == 'failed' and not result.get('objectId'), result
    assert '暂无可用于生成周报的工作记录' in result['message'] and '当前会话' in result['message']
    repeated = json.loads(await execute_business_action.coroutine(**args))
    assert repeated == result
    await assert_no_generated_report(setup[1], setup[2]['employee'])


async def test_legacy_empty_worker_job_does_not_call_model_or_overwrite_saved_report(setup):
    settings, sessions, users, _ = setup
    report, job, _ = await prepared(setup)
    async with sessions.begin() as db:
        (await db.get(Report, report.id)).content = CONTENT
        current = await db.get(Job, job.id)
        current.result = {**current.result, 'sourceIds': []}
    model = ReportModel()
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=model)
    assert model.calls == 0 and not model.reviews
    async with sessions() as db:
        current = await db.get(Job, job.id)
        assert current.state == 'failed' and '暂无可用于生成日报的工作记录' in current.error
        assert (await db.get(Report, report.id)).content == CONTENT


async def test_legacy_empty_receipt_cannot_claim_success_or_submit_existing_content(setup):
    await create(setup[3]['employee'], '方案', summary='初稿完成')
    context, _ = await mode_runtime(setup, 'full', '生成并提交本周周报')
    result = json.loads(await execute_business_action.coroutine(step=1, action='generate_report', runtime=SimpleNamespace(context=context), report_kind='weekly', report_date=today(), submit_after=True))
    assert result['state'] == 'running', result
    async with context.sessions.begin() as db:
        receipt = await db.get(BusinessAction, result['id'])
        job = await db.get(Job, receipt.result['jobId'])
        report = await db.get(Report, receipt.result['objectId'])
        report.content = CONTENT
        job.state, job.phase = 'succeeded', 'empty'
        await complete_action(db, setup[2]['employee'], receipt)
        assert receipt.state == 'failed' and receipt.action == 'generate_report'
        assert '暂无可用于生成周报的工作记录' in receipt.result['message']
        assert report.content == CONTENT and report.published_revision == 0
