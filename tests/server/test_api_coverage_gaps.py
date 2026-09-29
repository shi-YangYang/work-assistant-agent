"""Assertions for public readiness, desktop approval preview and report preparation."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import OperationalError

from app.db.idempotency import Idempotency
from app.modules.auth.models import DesktopAuthorization, DesktopSession
from app.modules.auth.sessions import digest
from app.modules.members.models import Company
from app.modules.reports.models import Report, ReportObligation
from app.modules.work.models import WorkRevision
from app.tasks.models import Job
from test_desktop_voiceprints import start
from test_full_system_acceptance import evidence

pytestmark = pytest.mark.asyncio


async def test_public_health_checks_database_and_recovers_without_disclosing_failure(setup, caplog):
    _, _, _, clients = setup
    app = clients['employee']._transport.app
    engine = app.state.sessions.kw['bind'].sync_engine
    statements, unavailable = [], False
    private_detail = 'controlled-private-database-error'

    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
        if unavailable:
            raise OperationalError(statement, parameters, RuntimeError(private_detail))

    event.listen(engine, 'before_cursor_execute', observe)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            ready = await client.get('/api/v1/health')
            assert ready.status_code == 200 and ready.json() == {'status': 'ready'}
            assert any('FROM company' in statement for statement in statements)
            assert ready.headers['Cache-Control'] == 'no-store'
            assert ready.headers['X-Request-ID'] and not ready.headers.get('Set-Cookie')
            unavailable = True
            failed = await client.get('/api/v1/health')
            assert failed.status_code == 503
            assert failed.json() == {'error': {'code': 'service_unavailable', 'message': '服务暂不可用，请稍后重试',
                                              'requestId': failed.headers['X-Request-ID']}}
            assert private_detail not in failed.text + caplog.text
            unavailable = False
            recovered = await client.get('/api/v1/health')
            assert recovered.status_code == 200 and recovered.json() == {'status': 'ready'}
    finally:
        event.remove(engine, 'before_cursor_execute', observe)
    evidence('http-health', {'anonymousReady': 200, 'databaseStatementObserved': True, 'controlledSqlFailure': 503,
                             'recovered': 200, 'privateDetailsExposed': False})


async def test_desktop_preview_shows_current_company_without_approving_the_request(setup):
    _, sessions, users, clients = setup
    client = clients['employee']
    request, verifier = await start(client)
    path = '/api/v1/auth/desktop/requests/' + request['requestId']
    async with sessions() as db:
        company = await db.get(Company, users['employee'].company_id)
        company_name = company.name
    for _ in range(2):
        preview = await client.get(path)
        assert preview.status_code == 200
        assert preview.json() == {'state': 'pending', 'expiresAt': request['expiresAt'], 'companyName': company_name}
        assert verifier not in preview.text and request['requestId'] not in preview.text
    async with sessions() as db:
        grant = await db.scalar(select(DesktopAuthorization).where(DesktopAuthorization.request_hash == digest(request['requestId'])))
        assert grant.state == 'pending' and grant.member_id is None and grant.company_id is None and grant.session_id is None
        assert not await db.scalar(select(func.count()).select_from(DesktopSession).where(DesktopSession.member_id == users['employee'].id))
    approved = await client.post(path, json={'approve': True})
    assert approved.status_code == 200
    assert (await client.get(path)).json() == {'state': 'approved', 'expiresAt': request['expiresAt'], 'companyName': company_name}
    exchanged = await client.post('/api/v1/desktop/login/exchange', json={'requestId': request['requestId'], 'verifier': verifier})
    assert exchanged.status_code == 200 and exchanged.json()['member']['id'] == users['employee'].id
    assert (await client.get(path)).status_code == 410
    evidence('http-desktop-preview', {'pendingPreviews': 2, 'previewDoesNotApprove': True,
                                      'approvedPreview': 200, 'exchange': 200, 'consumedPreview': 410})


async def test_prepare_obligation_creates_one_bound_report_and_replays_its_receipt(setup):
    _, sessions, users, clients = setup
    actor, client = users['employee'], clients['employee']
    instant = datetime.now(timezone.utc)
    work = await client.post('/api/v1/work-items', json={'title': '本期已确认工作', 'summary': '用于待办生成的事实', 'status': 'in_progress'},
                             headers={'Idempotency-Key': str(uuid4())})
    assert work.status_code == 201
    async with sessions.begin() as db:
        obligation = ReportObligation(company_id=actor.company_id, owner_id=actor.id, kind='daily',
            period=instant.date().isoformat(), period_end=instant.date().isoformat(), timezone='UTC', rule_revision=1,
            generate_at=instant, deadline_at=instant + timedelta(hours=1), reminders=True, before_minutes=30)
        db.add(obligation)
        await db.flush()
        identifier = obligation.id
        revision = await db.scalar(select(WorkRevision).where(WorkRevision.work_id == work.json()['id']))
        revision_id = revision.id
    path, key = f'/api/v1/report-obligations/{identifier}/prepare', str(uuid4())
    for role in ('peer', 'outsider'):
        assert (await clients[role].post(path, json={}, headers={'Idempotency-Key': str(uuid4())})).status_code == 404
    first = await client.post(path, json={}, headers={'Idempotency-Key': key})
    assert first.status_code == 200, first.text
    duplicate = await client.post(path, json={}, headers={'Idempotency-Key': key})
    assert duplicate.status_code == 200 and duplicate.json() == first.json()
    async with sessions() as db:
        report = await db.get(Report, first.json()['reportId'])
        job = await db.get(Job, first.json()['jobId'])
        bound = await db.get(ReportObligation, identifier)
        assert bound.report_id == report.id and bound.state == 'pending'
        assert report.owner_id == actor.id and report.period == instant.date().isoformat() and report.timezone == 'UTC'
        assert report.published_revision == 0 and not any(report.content.values())
        assert job.kind == 'report' and job.target_id == report.id and job.state == 'queued'
        assert job.result['sourceIds'] == [revision_id]
        assert await db.scalar(select(func.count()).select_from(Report).where(Report.owner_id == actor.id)) == 1
        assert await db.scalar(select(func.count()).select_from(Job).where(Job.owner_id == actor.id)) == 1
        assert await db.scalar(select(func.count()).select_from(Idempotency).where(Idempotency.owner_id == actor.id, Idempotency.key == key)) == 1
    evidence('http-obligation-prepare', {'initial': 200, 'repeat': 200, 'reports': 1, 'jobs': 1,
                                        'receipts': 1, 'confirmedSources': 1, 'foreignDenied': 2})
