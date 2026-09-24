"""Native-session isolation and enrollment publication boundaries; no real models."""
import asyncio
import base64
import hashlib
import io
import pytest
import secrets
import wave
from datetime import timedelta
from paa_server.db.base import now
from paa_server.modules.auth.models import DesktopAuthorization, DesktopSession
from paa_server.modules.auth.sessions import digest, revoke_member
from paa_server.modules.members.models import Member
from paa_server.modules.voiceprints.models import Voiceprint
from paa_server.tasks.voiceprints import process_once
from paa_voiceprints import MODEL_ID
from sqlalchemy import delete, select, update



pytestmark = pytest.mark.asyncio


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
        wav.writeframes(b'\0\0' * 16000)
    return output.getvalue()


async def start(client):
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    response = await client.post('/api/v1/desktop/login/start', json={'challenge': challenge})
    assert response.status_code == 200, response.text
    return response.json(), verifier


async def token(client):
    request, verifier = await start(client)
    result = await client.post('/api/v1/auth/desktop/requests/' + request['requestId'], json={'approve': True})
    assert result.status_code == 200, result.text
    response = await client.post('/api/v1/desktop/login/exchange', json={'requestId': request['requestId'], 'verifier': verifier})
    assert response.status_code == 200, response.text
    return response.json()['token']


async def enroll(client, member_id, revision=0, *, consent=True):
    return await client.post('/api/v1/settings/voiceprints/' + member_id, data={'consent': str(consent).lower(), 'expectedRevision': str(revision)}, files={'file': ('sample.wav', wav_bytes(), 'audio/wav')})


async def fake_extract(path, settings):
    assert path.is_file()
    return {'modelId': MODEL_ID, 'templates': [[1.] + [0.] * 255], 'speechSeconds': 7.2}


async def test_desktop_pkce_atomic_exchange_and_cookie_isolation(setup):
    _, sessions, users, c = setup
    client = c['admin']
    info = await client.get('/api/v1/desktop/info')
    assert info.json() == {'protocolVersion': 1, 'webOrigin': 'http://test'}
    request, verifier = await start(client)
    assert request['authorizationUrl'] == 'http://test/desktop/connect?request=' + request['requestId']
    assert (await client.get('/api/v1/desktop/me')).status_code == 401
    pending = await client.post('/api/v1/desktop/login/exchange', json={'requestId': request['requestId'], 'verifier': verifier})
    assert pending.status_code == 202 and pending.json() == {'state': 'pending'}
    wrong = await client.post('/api/v1/desktop/login/exchange', json={'requestId': request['requestId'], 'verifier': 'a' * 64})
    assert wrong.status_code == 403
    assert (await client.post('/api/v1/auth/desktop/requests/' + request['requestId'], json={'approve': True}, headers={'X-CSRF-Token': 'wrong'})).status_code == 403
    assert (await client.post('/api/v1/auth/desktop/requests/' + request['requestId'], json={'approve': True})).status_code == 200
    async with sessions.begin() as db:
        await db.execute(update(DesktopAuthorization).where(DesktopAuthorization.request_hash == digest(request['requestId'])).values(polled_at=None))
    responses = await asyncio.gather(*(client.post('/api/v1/desktop/login/exchange', json={'requestId': request['requestId'], 'verifier': verifier}) for _ in range(2)))
    assert sorted(r.status_code for r in responses) == [200, 410]
    success = next(r.json() for r in responses if r.status_code == 200)
    assert success['member']['id'] == users['admin'].id
    async with sessions() as db:
        rows = (await db.scalars(select(DesktopSession).where(DesktopSession.member_id == users['admin'].id))).all()
        assert len(rows) == 1 and rows[0].token_hash != success['token']
    headers = {'Authorization': 'Bearer ' + success['token']}
    assert (await client.get('/api/v1/desktop/me', headers=headers)).status_code == 200
    assert (await client.post('/api/v1/desktop/logout', headers=headers)).status_code == 200
    assert (await client.get('/api/v1/desktop/me', headers=headers)).status_code == 401


@pytest.mark.parametrize('change', ['revoke', 'disable', 'demote', 'web_logout'])
async def test_desktop_revocation_and_current_roles(setup, change):
    _, sessions, users, c = setup
    headers = {'Authorization': 'Bearer ' + await token(c['admin'])}
    async with sessions.begin() as db:
        actor = await db.get(Member, users['admin'].id)
        if change == 'revoke': await revoke_member(db, actor.id)
        if change == 'disable': actor.active = False
        if change == 'demote': actor.role = 'employee'
    if change == 'web_logout':
        assert (await c['admin'].post('/api/v1/auth/logout')).status_code == 200
    result = await c['admin'].get('/api/v1/desktop/voiceprints', headers=headers)
    assert result.status_code == (403 if change == 'demote' else 401)


async def test_desktop_authorization_needs_no_password_change_step(setup):
    _, _, users, c = setup
    headers = {'Authorization': 'Bearer ' + await token(c['admin'])}
    result = await c['admin'].get('/api/v1/desktop/me', headers=headers)
    assert result.status_code == 200 and result.json()['member']['id'] == users['admin'].id
    assert (await c['admin'].get('/api/v1/desktop/voiceprints', headers=headers)).status_code == 200


async def test_grant_expiry_denial_and_origin_boundaries(setup):
    _, sessions, _, c = setup
    request, verifier = await start(c['employee'])
    assert (await c['employee'].post('/api/v1/auth/desktop/requests/' + request['requestId'], json={'approve': False})).status_code == 200
    assert (await c['employee'].post('/api/v1/desktop/login/exchange', json={'requestId': request['requestId'], 'verifier': verifier})).status_code == 410
    async with sessions.begin() as db:
        await db.execute(update(DesktopAuthorization).where(DesktopAuthorization.request_hash == digest(request['requestId'])).values(state='pending', expires_at=now()-timedelta(seconds=1)))
    assert (await c['employee'].get('/api/v1/auth/desktop/requests/' + request['requestId'])).status_code == 410
    assert (await c['employee'].post('/api/v1/desktop/login/start', headers={'Origin': 'https://evil.example'}, json={'challenge': 'a'*43})).status_code == 403
    # Native exceptions never weaken the existing Web write boundary.
    del c['employee'].headers['Origin']
    assert (await c['employee'].post('/api/v1/auth/logout')).status_code == 403
    result = await c['employee'].post('/api/v1/desktop/login/start', json={'challenge': 'a'*43})
    assert result.status_code == 200
    async with sessions.begin() as db:
        await db.execute(delete(DesktopAuthorization).where(DesktopAuthorization.request_hash == digest(result.json()['requestId'])))


async def test_voiceprint_company_admin_boundaries_and_publish(setup):
    settings, sessions, users, c = setup
    member = users['employee'].id
    assert (await c['employee'].get('/api/v1/settings/voiceprints')).status_code == 403
    assert (await enroll(c['employee'], member)).status_code == 403
    assert (await enroll(c['admin'], users['outsider'].id)).status_code == 404
    assert (await enroll(c['admin'], member, consent=False)).status_code == 422
    listing = (await c['admin'].get('/api/v1/settings/voiceprints')).json()
    assert {m['memberId'] for m in listing['items']} == {users[x].id for x in ('admin', 'employee', 'peer')}
    assert all('templates' not in m for m in listing['items'])
    result = await enroll(c['admin'], member)
    assert result.status_code == 202 and result.json()['state'] == 'queued'
    assert (await enroll(c['admin'], member, revision=1)).status_code == 409
    header = {'Authorization': 'Bearer ' + await token(c['admin'])}
    assert (await c['admin'].get('/api/v1/desktop/voiceprints', headers=header)).json()['profiles'] == []
    assert await process_once(sessions, settings, extractor=fake_extract)
    ready = (await c['admin'].get('/api/v1/desktop/voiceprints', headers=header)).json()
    assert ready['profiles'] == [{'memberId': member, 'name': users['employee'].name, 'templates': [[1.] + [0.] * 255]}]
    assert (await c['outsider'].get('/api/v1/settings/voiceprints/' + member + '/audio')).status_code == 403
    assert (await c['admin'].get('/api/v1/settings/voiceprints/' + member + '/audio')).content == wav_bytes()
    # Failed replacement preserves the published template and private old original.
    assert (await enroll(c['admin'], member, revision=1)).status_code == 202
    async def fail(*args): raise ValueError('声纹模型未就绪，请检查模型文件')
    assert await process_once(sessions, settings, extractor=fail)
    after = (await c['admin'].get('/api/v1/desktop/voiceprints', headers=header)).json()
    assert after == ready
    failed = next(m for m in (await c['admin'].get('/api/v1/settings/voiceprints')).json()['items'] if m['memberId'] == member)
    assert failed['state'] == 'failed' and failed['ready'] and '模型' in failed['error']
    assert (await c['admin'].post('/api/v1/settings/voiceprints/' + member + '/retry')).status_code == 202
    assert await process_once(sessions, settings, extractor=fake_extract)
    assert (await c['admin'].delete('/api/v1/settings/voiceprints/' + member)).status_code == 200
    assert (await c['admin'].get('/api/v1/desktop/voiceprints', headers=header)).json()['profiles'] == []
    assert not list((settings.media_dir / 'voiceprints').iterdir())


async def test_delete_inflight_cannot_republish_and_inactive_hidden(setup):
    settings, sessions, users, c = setup
    member = users['admin'].id
    assert (await enroll(c['admin'], member)).status_code == 202
    async def delete_while_processing(path, unused):
        assert (await c['admin'].delete('/api/v1/settings/voiceprints/' + member)).status_code == 200
        return {'modelId': MODEL_ID, 'templates': [[1.] + [0.] * 255], 'speechSeconds': 10}
    await process_once(sessions, settings, extractor=delete_while_processing)
    async with sessions() as db:
        assert await db.scalar(select(Voiceprint).where(Voiceprint.member_id == member)) is None
    assert not list((settings.media_dir / 'voiceprints').iterdir())


async def test_version_mismatch_is_actionable_and_inactive_is_not_synced(setup):
    settings, sessions, users, c = setup
    member = users['employee'].id
    assert (await enroll(c['admin'], member)).status_code == 202
    await process_once(sessions, settings, extractor=fake_extract)
    headers = {'Authorization': 'Bearer ' + await token(c['admin'])}
    async with sessions.begin() as db:
        item = await db.scalar(select(Voiceprint).where(Voiceprint.member_id == member))
        item.model_id = 'old-engine-v0'
    listing = (await c['admin'].get('/api/v1/settings/voiceprints')).json()
    item = next(row for row in listing['items'] if row['memberId'] == member)
    assert item['state'] == 'incompatible' and not item['ready'] and '重新上传' in item['error']
    result = await c['admin'].get('/api/v1/desktop/voiceprints', headers=headers)
    assert result.status_code == 409 and result.json()['error']['code'] == 'voiceprint_model_mismatch'
    async with sessions.begin() as db:
        actor = await db.get(Member, member)
        actor.active = False
        outsider = await db.get(Member, users['outsider'].id)
        outsider.role = 'admin'
    assert (await c['admin'].get('/api/v1/desktop/voiceprints', headers=headers)).json()['profiles'] == []
    foreign = {'Authorization': 'Bearer ' + await token(c['outsider'])}
    assert (await c['outsider'].get('/api/v1/desktop/voiceprints', headers=foreign)).json()['profiles'] == []
    assert (await c['outsider'].get('/api/v1/settings/voiceprints/' + member + '/audio')).status_code == 404
    assert (await c['outsider'].delete('/api/v1/settings/voiceprints/' + member)).status_code == 404
    assert (await c['admin'].delete('/api/v1/settings/voiceprints/' + member)).status_code == 200


async def test_subprocess_cancellation_reaps_inference(tmp_path, monkeypatch):
    import sys
    from dataclasses import replace
    from paa_server.core.config import Settings
    from paa_server.tasks.voiceprints import extract
    runner = tmp_path / 'runner.py'
    runner.write_text('import sys,time\nprint("ready",flush=True)\ntime.sleep(60)\n')
    actual_spawn = asyncio.create_subprocess_exec
    child_started = asyncio.Event()
    children = []
    async def spawn(*args, **kwargs):
        child = await actual_spawn(sys.executable, str(runner), **kwargs)
        children.append(child)
        child_started.set()
        return child
    async def audio(*args): return wav_bytes(), 1
    monkeypatch.setattr('paa_server.tasks.voiceprints.audio_wav', audio)
    monkeypatch.setattr('paa_server.tasks.voiceprints.asyncio.create_subprocess_exec', spawn)
    task = asyncio.create_task(extract(tmp_path / 'sample', Settings()))
    await asyncio.wait_for(child_started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert children[0].returncode is not None
