"""Explicit regeneration creates a new identity without reviving old work."""
import asyncio
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select

from app.agent.actions.operations import execute
from app.db.base import now
from app.db.idempotency import Idempotency
from app.modules.members.models import Member
from app.modules.reports.models import Report, ReportEligibility, ReportNotification, ReportObligation, ReportSchedule
from app.modules.reports.scheduling.schedule import eligibility_changed, materialize
from app.modules.reports.service import ensure_report
from app.modules.work.models import WorkItem
from app.tasks.models import Job
from app.tasks.processing.handlers import process_job
from app.tasks.runtime.queue import claim
from _support.agent.business_actions import create, finish
from _support.agent.execution_permissions import mode_runtime
from _support.http.company import keyed
from _support.work.report_reliability import CONTENT, ReportModel

pytestmark = pytest.mark.asyncio


def today():
    return now().astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()


async def generate(client, kind='weekly', *, headers=None):
    response = await client.post('/api/v1/reports/generate', json={'kind': kind, 'date': today()}, headers=headers or keyed())
    assert response.status_code == 202, response.text
    return response.json()


async def remove(client, identifier):
    saved = await client.get('/api/v1/reports/' + identifier)
    assert saved.status_code == 200, saved.text
    response = await client.request('DELETE', '/api/v1/reports/' + identifier, json={'expectedRevision': saved.json()['managementRevision']})
    assert response.status_code == 200, response.text
    return saved.json()


async def obligation_for(sessions, identifier):
    async with sessions.begin() as db:
        report = await db.get(Report, identifier)
        obligation = ReportObligation(company_id=report.company_id, owner_id=report.owner_id, kind=report.kind,
            period=report.period, period_end=report.period_end, timezone=report.timezone, rule_revision=1,
            generate_at=now(), deadline_at=now() + timedelta(hours=1), reminders=True, before_minutes=30,
            report_id=report.id)
        db.add(obligation)
        await db.flush()
        return obligation


@pytest.mark.parametrize('kind', ['weekly'])
async def test_api_delete_rebuild_worker_submit_and_old_identity_isolation(setup, kind):
    settings, sessions, users, clients = setup
    client = clients['employee']
    await create(client, '方案', summary='方案初稿已完成', status='done')
    first = await generate(client, kind)
    old_job = await claim(sessions, users['employee'].id)
    old = await remove(client, first['reportId'])
    second = await generate(client, kind)
    assert second['reportId'] != first['reportId'] and second['jobId'] != first['jobId']
    stale_model = ReportModel()
    await process_job(old_job, sessions, settings, None, model=stale_model)
    assert stale_model.calls == 0
    assert (await client.post('/api/v1/jobs/' + old_job.id + '/retry', json={})).status_code == 404
    for who in ('employee', 'admin', 'peer', 'outsider'):
        assert (await clients[who].get('/api/v1/reports/' + first['reportId'])).status_code == 404
    # An old delete/submit is still about the old ID, even when a fresh report exists.
    assert (await client.request('DELETE', '/api/v1/reports/' + first['reportId'], json={'expectedRevision': old['revision']})).status_code == 200
    assert (await client.post('/api/v1/reports/' + first['reportId'] + '/submit', json={'expectedRevision': old['revision']}, headers=keyed())).status_code == 404
    model = ReportModel()
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=model)
    saved = (await client.get('/api/v1/reports/' + second['reportId'])).json()
    assert saved['content'] == CONTENT and saved['publishedRevision'] == 0 and saved['candidate'] is None
    assert model.calls == 1 and len(model.reviews) == 0
    submit_headers = keyed()
    assert (await client.post('/api/v1/reports/' + second['reportId'] + '/submit', json={'expectedRevision': saved['revision']}, headers=submit_headers)).status_code == 200
    assert (await clients['admin'].get('/api/v1/reports/' + second['reportId'])).status_code == 200
    await remove(clients['admin'], second['reportId'])
    third = await generate(client, kind)
    assert third['reportId'] not in (first['reportId'], second['reportId'])
    assert (await clients['admin'].get('/api/v1/reports/' + third['reportId'])).status_code == 404
    assert (await client.post('/api/v1/reports/' + second['reportId'] + '/submit', json={'expectedRevision': saved['revision']}, headers=submit_headers)).status_code == 404
    async with sessions() as db:
        reports = list((await db.scalars(select(Report).where(Report.owner_id == users['employee'].id))).all())
        assert len(reports) == 3 and sum(not row.deleted for row in reports) == 1
        assert all(row.content == {} and row.candidate is None and row.source_ids == [] for row in reports if row.deleted)
        live = await db.get(Job, old_job.id)
        assert live.state == 'cancelled' and live.fence > old_job.fence


async def test_late_model_result_after_deletion_cannot_write_new_report(setup):
    settings, sessions, users, clients = setup
    client = clients['employee']
    await create(client, '方案', summary='初稿完成')
    first = await generate(client)
    replacement = {}
    async def replace_report():
        await remove(client, first['reportId'])
        replacement.update(await generate(client))
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=ReportModel(callback=replace_report))
    async with sessions() as db:
        old = await db.get(Report, first['reportId'])
        new = await db.get(Report, replacement['reportId'])
        assert old.deleted and old.content == {} and not any(new.content.values())
        assert (await db.get(Job, replacement['jobId'])).state == 'queued'


async def test_multiple_tombstones_concurrent_generation_and_scheduled_active_precedence(setup):
    _, sessions, users, clients = setup
    client, actor = clients['employee'], users['employee']
    await create(client, '方案', summary='初稿完成')
    first = await generate(client)
    await remove(client, first['reportId'])
    second = await generate(client)
    await remove(client, second['reportId'])
    async with sessions.begin() as db:
        report, job = await ensure_report(db, actor, 'weekly', date.fromisoformat(today()), scheduled=True)
        assert report.deleted and job is None
    shared = keyed()
    results = await asyncio.gather(*(generate(client, headers=shared if index < 2 else keyed()) for index in range(4)))
    assert all(value == results[0] for value in results)
    async with sessions.begin() as db:
        report, job = await ensure_report(db, actor, 'weekly', date.fromisoformat(today()), scheduled=True)
        assert report.id == results[0]['reportId'] and job.id == results[0]['jobId']
        rows = list((await db.scalars(select(Report).where(Report.owner_id == actor.id))).all())
        assert len(rows) == 3 and sum(not row.deleted for row in rows) == 1
        with pytest.raises(__import__('fastapi').HTTPException) as error:
            await ensure_report(db, actor, 'weekly', date.fromisoformat(today()), instructions='新的要求')
        assert error.value.status_code == 409


@pytest.mark.parametrize('entry', ['generate', 'prepare', 'assistant'])
async def test_explicit_regeneration_restores_only_deleted_obligation(setup, entry):
    settings, sessions, users, clients = setup
    client = clients['employee']
    await create(client, '方案', summary='初稿完成')
    first = await generate(client)
    obligation = await obligation_for(sessions, first['reportId'])
    prepare_url = f'/api/v1/report-obligations/{obligation.id}/prepare'
    headers = keyed()
    prepared = await client.post(prepare_url, json={}, headers=headers)
    assert prepared.status_code == 200
    async with sessions.begin() as db:
        cached = await db.scalar(select(Idempotency).where(Idempotency.owner_id == users['employee'].id, Idempotency.action == 'prepare-obligation:' + obligation.id))
        historical = {key: getattr(cached, key) for key in ('company_id', 'owner_id', 'action', 'key', 'digest', 'response')}
        db.add(ReportNotification(company_id=obligation.company_id, owner_id=obligation.owner_id, obligation_id=obligation.id, stage='ready'))
    await remove(client, first['reportId'])
    async with sessions.begin() as db:
        assert not await db.scalar(select(Idempotency.id).where(Idempotency.action == historical['action'], Idempotency.owner_id == users['employee'].id))
        assert not await db.scalar(select(ReportNotification.id).where(ReportNotification.obligation_id == obligation.id))
        # Recreate the historical cache left by deployments before this fix.
        db.add(Idempotency(**historical))
    if entry == 'prepare':
        result = await client.post(prepare_url, json={}, headers=headers)
        assert result.status_code == 200, result.text
        second = result.json()
    elif entry == 'assistant':
        context, _ = await mode_runtime(setup, 'full', '重新生成本周的周报')
        result = await execute(context, step=1, action='generate_report', report_kind='weekly', report_date=obligation.period, obligation_id=obligation.id)
        assert result['state'] == 'running', result
        second = {'reportId': result['objectId'], 'jobId': result['job']['id']}
        await finish(context)
    else:
        second = await generate(client)
    assert second['reportId'] != first['reportId']
    async with sessions() as db:
        restored = await db.get(ReportObligation, obligation.id)
        assert restored.state == 'pending' and restored.cancel_reason is None
        assert restored.report_id == second['reportId'] and restored.submitted_at is None
    replay = await client.post(prepare_url, json={}, headers=headers)
    assert replay.status_code == 200 and replay.json() == second
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=ReportModel())
    saved = (await client.get('/api/v1/reports/' + second['reportId'])).json()
    assert (await client.post('/api/v1/reports/' + second['reportId'] + '/submit', json={'expectedRevision': saved['revision']}, headers=keyed())).status_code == 200
    async with sessions() as db:
        assert (await db.get(ReportObligation, obligation.id)).state == 'submitted'


async def test_no_sources_does_not_restore_cancelled_obligation(setup):
    _, sessions, users, clients = setup
    client = clients['employee']
    work = await create(client, '方案', summary='初稿完成')
    first = await generate(client, 'weekly')
    obligation = await obligation_for(sessions, first['reportId'])
    await remove(client, first['reportId'])
    async with sessions.begin() as db:
        (await db.get(WorkItem, work['id'])).deleted = True
    missing = await client.post(f'/api/v1/report-obligations/{obligation.id}/prepare', json={}, headers=keyed())
    assert missing.status_code == 422 and missing.json()['error']['code'] == 'report_sources_empty'
    assert obligation.period in missing.json()['error']['message'] and obligation.period_end in missing.json()['error']['message']
    async with sessions() as db:
        row = await db.get(ReportObligation, obligation.id)
        assert row.state == 'cancelled' and row.cancel_reason == 'report_deleted' and row.report_id == first['reportId']
        assert list((await db.scalars(select(Report.id).where(Report.owner_id == users['employee'].id))).all()) == [first['reportId']]
        assert list((await db.scalars(select(Job.id).where(Job.owner_id == users['employee'].id, Job.kind == 'report'))).all()) == [first['jobId']]


@pytest.mark.parametrize('reason', ['unknown', 'eligibility_revoked'])
async def test_unrelated_cancellation_survives_explicit_generation(setup, reason):
    _, sessions, users, clients = setup
    client, actor = clients['employee'], users['employee']
    await create(client, '方案', summary='初稿完成')
    first = await generate(client)
    obligation = await obligation_for(sessions, first['reportId'])
    await remove(client, first['reportId'])
    async with sessions.begin() as db:
        if reason == 'eligibility_revoked':
            member = await db.get(Member, actor.id)
            member.active = False
            await eligibility_changed(db, member)
            member.active = True
            await eligibility_changed(db, member)
        else:
            (await db.get(ReportObligation, obligation.id)).cancel_reason = reason
    denied = await client.post(f'/api/v1/report-obligations/{obligation.id}/prepare', json={}, headers=keyed())
    assert denied.status_code == 409
    second = await generate(client)
    async with sessions() as db:
        row = await db.get(ReportObligation, obligation.id)
        assert row.state == 'cancelled' and row.cancel_reason == reason and row.report_id == first['reportId']
        assert not (await db.get(Report, second['reportId'])).deleted


async def test_materialize_prefers_active_report_and_retains_deleted_cancellation(setup):
    _, sessions, users, clients = setup
    client, actor = clients['employee'], users['employee']
    await create(client, '方案', summary='初稿完成')
    first = await generate(client)
    await remove(client, first['reportId'])
    second = await generate(client)
    await remove(client, second['reportId'])
    start = date.fromisoformat(today())
    start -= timedelta(days=start.weekday())
    async with sessions.begin() as db:
        db.add(ReportEligibility(company_id=actor.company_id, owner_id=actor.id, starts_at=datetime.combine(start - timedelta(days=1), time.min, ZoneInfo('Asia/Shanghai'))))
        await db.flush()
        schedule = ReportSchedule(company_id=actor.company_id, kind='weekly', revision=1, timezone='Asia/Shanghai',
            rule={'days': [0], 'generateTime': '17:00', 'deadline': '18:00'}, effective_period=today(), next_period=today())
        await materialize(db, schedule, start, 50)
        obligation = await db.scalar(select(ReportObligation).where(ReportObligation.owner_id == actor.id))
        assert obligation.state == 'cancelled' and obligation.cancel_reason == 'report_deleted'
        await db.execute(delete(ReportObligation).where(ReportObligation.id == obligation.id))
    third = await generate(client)
    async with sessions.begin() as db:
        await materialize(db, schedule, start, 50)
        obligation = await db.scalar(select(ReportObligation).where(ReportObligation.owner_id == actor.id))
        assert obligation.state == 'pending' and obligation.report_id == third['reportId']


async def test_old_assistant_receipt_does_not_follow_replacement_or_submit_it(setup):
    settings, sessions, users, clients = setup
    client = clients['employee']
    await create(client, '方案', summary='初稿完成')
    context, sent = await mode_runtime(setup, 'full', '生成并提交本周的周报')
    old = await execute(context, step=1, action='generate_report', report_kind='weekly', report_date=today(), submit_after=True)
    assert old['state'] == 'running'
    await finish(context)
    await remove(client, old['objectId'])
    new = await generate(client)
    await process_job(await claim(sessions, users['employee'].id), sessions, settings, None, model=ReportModel())
    message = (await client.get('/api/v1/messages/' + sent['messageId'])).json()
    assert message['actions'][0]['state'] == 'unavailable'
    assert not message['actions'][0].get('objectId')
    async with sessions() as db:
        from app.modules.operations.models import BusinessAction
        receipt = await db.get(BusinessAction, old['id'])
        assert receipt.result['objectId'] == old['objectId']
        assert (await db.get(Report, new['reportId'])).published_revision == 0
