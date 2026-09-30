"""Role and tenant boundaries for remaining administrative HTTP operations."""
import pytest
from sqlalchemy import func, select

from app.modules.auth.models import DesktopSession, DingTalkAuthorization
from app.modules.auth.sessions import digest
from app.modules.members.models import Member
from app.modules.voiceprints.models import Voiceprint
from app.tasks.processing.voiceprints import process_once
from test_desktop_voiceprints import enroll, token
from test_dingtalk import enable
from test_model_services import create, route


pytestmark = pytest.mark.asyncio


async def test_routing_admin_only_and_report_rules_employee_reads_own_company(setup):
    _, sessions, users, clients = setup
    saved = await create(clients['admin'])
    assigned = await clients['admin'].put('/api/v1/settings/model-routing', json=route(saved))
    assert assigned.status_code == 200
    assert (await clients['employee'].get('/api/v1/settings/model-routing')).status_code == 403
    own = await clients['admin'].get('/api/v1/settings/model-routing')
    assert own.status_code == 200 and own.json() == assigned.json()
    async with sessions.begin() as db:
        (await db.get(Member, users['outsider'].id)).role = 'admin'
    other = await clients['outsider'].get('/api/v1/settings/model-routing')
    assert other.status_code == 200
    assert other.json()['assistant'] is None and other.json()['environment'] is None
    assert saved['id'] not in other.text
    rules = (await clients['admin'].get('/api/v1/settings/report-rules')).json()
    body = {key: value for key, value in rules.items() if key not in ('revision', 'effectivePeriods')}
    body.update(expectedRevision=rules['revision'], timezone='Asia/Tokyo')
    changed = await clients['admin'].put('/api/v1/settings/report-rules', json=body)
    assert changed.status_code == 200
    # Role-403 is N/A: employees must read their own company reporting schedule.
    employee = await clients['employee'].get('/api/v1/settings/report-rules')
    outsider = await clients['outsider'].get('/api/v1/settings/report-rules')
    assert employee.status_code == outsider.status_code == 200
    assert employee.json() == changed.json()
    assert outsider.json()['timezone'] != 'Asia/Tokyo'
    assert (await clients['admin'].get('/api/v1/settings/model-routing')).json() == assigned.json()


async def test_voiceprint_retry_cleanup_and_member_impact_cannot_cross_admin_scope(setup):
    settings, sessions, users, clients = setup
    member_id = users['employee'].id
    assert (await enroll(clients['admin'], member_id)).status_code == 202
    async def fail(*args):
        raise ValueError('受控提取失败')
    assert await process_once(sessions, settings, extractor=fail)
    async with sessions.begin() as db:
        (await db.get(Member, users['outsider'].id)).role = 'admin'
        item = await db.scalar(select(Voiceprint).where(Voiceprint.member_id == member_id))
        before = (item.state, item.revision, item.pending_path, item.error)
        assert item.state == 'failed' and item.pending_path
    retry_path = '/api/v1/settings/voiceprints/' + member_id + '/retry'
    deletion_path = '/api/v1/members/' + member_id + '/deletion'
    assert (await clients['employee'].post(retry_path)).status_code == 403
    assert (await clients['outsider'].post(retry_path)).status_code == 404
    assert (await clients['employee'].get(deletion_path)).status_code == 403
    assert (await clients['outsider'].get(deletion_path)).status_code == 404
    assert (await clients['employee'].get('/api/v1/settings/voiceprints/cleanup')).status_code == 403
    outsider = await clients['outsider'].get('/api/v1/settings/voiceprints/cleanup')
    assert outsider.status_code == 200
    assert outsider.json() == {'legacy': {'members': 0, 'voiceprints': 0, 'recordings': 0}, 'pending': 0, 'failed': 0}
    preview = await clients['admin'].get(deletion_path)
    assert preview.status_code == 200 and preview.json() == {'voiceprints': 1, 'recordings': 1}
    async with sessions() as db:
        item = await db.scalar(select(Voiceprint).where(Voiceprint.member_id == member_id))
        assert (item.state, item.revision, item.pending_path, item.error) == before
        assert not (await db.get(Member, member_id)).deleted
    response = await clients['admin'].post(retry_path)
    assert response.status_code == 202 and response.json()['state'] == 'queued'
    async with sessions() as db:
        item = await db.scalar(select(Voiceprint).where(Voiceprint.member_id == member_id))
        assert item.revision == before[1] + 1 and item.pending_path == before[2]
        assert item.error == ''


async def test_dingtalk_probe_rejects_employee_without_creating_authorization(setup, monkeypatch):
    _, sessions, users, clients = setup
    provider = await enable(setup, monkeypatch, enabled=False)
    path = '/api/v1/settings/login/dingtalk/probe'
    assert (await clients['employee'].post(path, json={})).status_code == 403
    async with sessions.begin() as db:
        (await db.get(Member, users['outsider'].id)).role = 'admin'
    assert (await clients['outsider'].post(path, json={})).status_code == 409
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(DingTalkAuthorization).where(DingTalkAuthorization.company_id.in_([users['admin'].company_id, users['outsider'].company_id]))) == 0
    response = await clients['admin'].post(path, json={})
    assert response.status_code == 200 and response.json()['url'].startswith('https://login.dingtalk.com/')
    assert 'controlled-app-secret' not in response.text
    async with sessions() as db:
        rows = (await db.scalars(select(DingTalkAuthorization).where(DingTalkAuthorization.company_id == users['admin'].company_id))).all()
        assert len(rows) == 1 and rows[0].member_id == users['admin'].id and rows[0].purpose == 'probe'
    assert provider.calls == []


async def test_desktop_logout_requires_own_valid_bearer_and_keeps_other_sessions(setup):
    _, sessions, users, clients = setup
    own = await token(clients['employee'])
    other = await token(clients['peer'])
    path = '/api/v1/desktop/logout'
    assert (await clients['employee'].post(path)).status_code == 401
    assert (await clients['employee'].post(path, headers={'Authorization': 'Bearer unknown-controlled-token'})).status_code == 401
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(DesktopSession).where(DesktopSession.member_id.in_([users['employee'].id, users['peer'].id]))) == 2
    response = await clients['employee'].post(path, headers={'Authorization': 'Bearer ' + own})
    assert response.status_code == 200 and response.json() == {'ok': True}
    assert (await clients['employee'].post(path, headers={'Authorization': 'Bearer ' + own})).status_code == 401
    alive = await clients['peer'].get('/api/v1/desktop/me', headers={'Authorization': 'Bearer ' + other})
    assert alive.status_code == 200 and alive.json()['member']['id'] == users['peer'].id
    async with sessions() as db:
        assert await db.scalar(select(DesktopSession).where(DesktopSession.token_hash == digest(own))) is None
        assert await db.scalar(select(DesktopSession).where(DesktopSession.token_hash == digest(other))) is not None
