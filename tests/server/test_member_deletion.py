from datetime import timedelta

import pytest
from sqlalchemy import func, select

from paa_server.models import DesktopSession, Job, Member, Message, ReportEligibility, ReportNotification, ReportObligation, Session, Voiceprint, now
from test_search_metrics_feedback import content, work
from test_team_workspace import DAY, RANGE, report

pytestmark = pytest.mark.asyncio


async def test_delete_member_revokes_access_stops_work_and_preserves_history(setup):
    _, sessions, users, clients = setup
    employee = users['employee']
    async with sessions.begin() as db:
        task = await work(db, employee, content('保留历史工作'), DAY)
        submitted = await report(db, employee, '2026-09-12')
        original = Message(company_id=employee.company_id, owner_id=employee.id, text='保留原始消息')
        db.add(original)
        await db.flush()
        job = Job(company_id=employee.company_id, owner_id=employee.id, kind='message', target_id=original.id, state='running', fence=2, lease_until=now() + timedelta(minutes=1))
        eligibility = ReportEligibility(company_id=employee.company_id, owner_id=employee.id, starts_at=now() - timedelta(days=1))
        obligation = ReportObligation(company_id=employee.company_id, owner_id=employee.id, kind='daily', period='2026-09-13', period_end='2026-09-13', timezone='Asia/Shanghai', rule_revision=1, generate_at=now(), deadline_at=now(), reminders=True, before_minutes=0)
        enrollment = Voiceprint(company_id=employee.company_id, member_id=employee.id, consent_by=users['admin'].id, state='processing', revision=2)
        db.add_all([job, eligibility, obligation, enrollment])
        await db.flush()
        db.add(ReportNotification(company_id=employee.company_id, owner_id=employee.id, obligation_id=obligation.id, stage='ready'))
        session = await db.scalar(select(Session).where(Session.member_id == employee.id))
        db.add(DesktopSession(company_id=employee.company_id, member_id=employee.id, session_id=session.id, token_hash='a' * 64, expires_at=now() + timedelta(hours=1)))
    path = '/api/v1/members/' + employee.id
    admin = clients['admin']
    for forbidden in (clients['employee'], clients['outsider']):
        assert (await forbidden.delete(path)).status_code == 403
    for identifier in (users['admin'].id, users['outsider'].id):
        assert (await admin.delete('/api/v1/members/' + identifier)).status_code == 404
    assert (await admin.delete(path, headers={'X-CSRF-Token': 'wrong'})).status_code == 403
    for _ in range(2):
        response = await admin.delete(path)
        assert response.status_code == 200, response.text
    assert employee.id not in [m['id'] for m in (await admin.get('/api/v1/members')).json()['items']]
    assert (await clients['employee'].get('/api/v1/auth/me')).status_code == 401
    assert (await clients['employee'].post('/api/v1/auth/login', json={'username': employee.username, 'password': 'controlled-test-password'})).status_code == 401
    assert (await admin.patch(path, json={'active': True})).status_code == 404
    assert (await admin.post(path + '/reset-password', json={'password': 'controlled-test-password'})).status_code == 404
    recreated = await admin.post('/api/v1/members', json={'username': employee.username, 'name': '重新创建的员工', 'password': 'new-controlled-password', 'role': 'employee'})
    assert recreated.status_code == 201, recreated.text
    assert recreated.json()['id'] != employee.id and recreated.json()['username'] == employee.username
    async with sessions() as db:
        stored = await db.get(Member, employee.id)
        assert stored.deleted and not stored.active and stored.password_hash is None
        assert stored.username != employee.username
        assert not await db.scalar(select(Session.id).where(Session.member_id == employee.id))
        assert not await db.scalar(select(DesktopSession.id).where(DesktopSession.member_id == employee.id))
        assert (await db.get(Job, job.id)).state == 'cancelled'
        assert (await db.get(Job, job.id)).fence == 3
        assert (await db.get(Voiceprint, enrollment.id)).revision == 3
        assert (await db.get(Voiceprint, enrollment.id)).state == 'failed'
        assert (await db.get(ReportEligibility, eligibility.id)).ends_at
        assert (await db.get(ReportObligation, obligation.id)).state == 'cancelled'
        assert not await db.scalar(select(ReportNotification.id).where(ReportNotification.owner_id == employee.id))
        assert not (await db.get(Message, original.id)).deleted
    assert (await admin.get('/api/v1/work-items/' + task.id)).status_code == 200
    assert (await admin.get('/api/v1/reports/' + submitted.id)).status_code == 200
    for view in ('work', 'reports'):
        active = (await admin.get('/api/v1/team/workspace/' + view, params=RANGE)).json()
        retained = (await admin.get('/api/v1/team/workspace/' + view, params={**RANGE, 'members': 'all'})).json()
        assert active['total'] == 0 and retained['total'] == 1
        assert retained['items'][0]['member']['deleted']
    assert employee.id not in [m['memberId'] for m in (await admin.get('/api/v1/settings/voiceprints')).json()['items']]
    # Retrying a previous deletion must not affect the newly created account.
    assert (await admin.delete(path)).status_code == 200
    from test_dingtalk import browser, app_for, logged_in
    async with browser(app_for(clients)) as client:
        assert (await client.post('/api/v1/auth/login', json={'username': employee.username, 'password': 'controlled-test-password'})).status_code == 401
        login = await client.post('/api/v1/auth/login', json={'username': employee.username, 'password': 'new-controlled-password'})
        assert login.status_code == 200 and login.json()['member']['id'] == recreated.json()['id']
        await logged_in(client)
        assert (await client.post('/api/v1/auth/password', json={'currentPassword': 'new-controlled-password', 'newPassword': 'changed-controlled-password'})).status_code == 200
        assert (await client.post('/api/v1/auth/login', json={'username': employee.username, 'password': 'changed-controlled-password'})).status_code == 200
        assert (await client.get('/api/v1/work-items')).json()['items'] == []
        assert (await client.get('/api/v1/reports')).json()['items'] == []
        assert (await client.get('/api/v1/work-items/' + task.id)).status_code == 404
        assert (await client.get('/api/v1/reports/' + submitted.id)).status_code == 404


async def test_deleted_dingtalk_member_can_register_again_without_old_data(setup, monkeypatch):
    from test_dingtalk import enable, browser, app_for, begin, complete, logged_in
    _, sessions, users, clients = setup
    await enable(setup, monkeypatch)
    async with browser(app_for(clients)) as client:
        response = await complete(client, await begin(client))
        assert response.headers['location'].endswith('dingtalk=logged-in')
        identity = await logged_in(client)
        identifier = identity['member']['id']
        async with sessions.begin() as db:
            before = await db.scalar(select(func.count()).select_from(Member).where(Member.company_id == users['admin'].company_id))
            old_member = await db.get(Member, identifier)
            task = await work(db, old_member, content('旧钉钉账号的工作'), DAY)
            submitted = await report(db, old_member, '2026-09-12')
        assert (await clients['admin'].delete('/api/v1/members/' + identifier)).status_code == 200
        assert (await client.get('/api/v1/auth/me')).status_code == 401
        response = await complete(client, await begin(client))
        assert response.headers['location'].endswith('dingtalk=logged-in')
        fresh = await logged_in(client)
        assert fresh['member']['id'] != identifier and fresh['member']['role'] == 'employee'
        assert (await client.get('/api/v1/work-items')).json()['items'] == []
        assert (await client.get('/api/v1/reports')).json()['items'] == []
        assert (await client.get('/api/v1/work-items/' + task.id)).status_code == 404
        assert (await client.get('/api/v1/reports/' + submitted.id)).status_code == 404
        assert (await clients['admin'].delete('/api/v1/members/' + identifier)).status_code == 200
        assert (await client.get('/api/v1/auth/me')).status_code == 200
        async with sessions() as db:
            from paa_server.models import DingTalkIdentity
            after = await db.scalar(select(func.count()).select_from(Member).where(Member.company_id == users['admin'].company_id))
            assert after == before + 1
            assert (await db.get(Member, identifier)).deleted
            link = await db.scalar(select(DingTalkIdentity).where(DingTalkIdentity.company_id == users['admin'].company_id))
            assert link.member_id == fresh['member']['id']
