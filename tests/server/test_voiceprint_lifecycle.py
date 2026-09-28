import asyncio
import json
import math
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.modules.members.models import Member
from app.modules.voiceprints.cleanup import drain, remove_enrollment
from app.modules.voiceprints.models import Voiceprint, VoiceprintCleanup
from app.tasks.voiceprints import extract, process_once
from paa_voiceprints import MODEL_ID
from test_desktop_voiceprints import enroll, fake_extract, wav_bytes

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('oversize', [False, True])
async def test_chunked_extraction_reads_eof_and_bounds_total(tmp_path, monkeypatch, oversize):
    vector = [math.sin(i + 1) for i in range(256)]
    norm = math.sqrt(sum(n * n for n in vector))
    result = {'modelId': MODEL_ID, 'templates': [[n / norm for n in vector]] * 12, 'speechSeconds': 72}
    payload = json.dumps(result) if not oversize else ' ' * (256 * 1024 + 1)
    runner = tmp_path / 'runner.py'
    runner.write_text('import sys,time\npayload=' + repr(payload) + '\nfor offset in range(0,len(payload),1000):\n sys.stdout.write(payload[offset:offset+1000]);sys.stdout.flush();time.sleep(.001)\n')
    spawn = asyncio.create_subprocess_exec
    children = []
    async def fake_spawn(*args, **kwargs):
        child = await spawn(sys.executable, str(runner), **kwargs)
        children.append(child)
        return child
    async def audio(*args): return wav_bytes(), 72
    monkeypatch.setattr('app.tasks.voiceprints.asyncio.create_subprocess_exec', fake_spawn)
    monkeypatch.setattr('app.tasks.voiceprints.audio_wav', audio)
    if oversize:
        with pytest.raises(ValueError, match='结果异常'):
            await extract(tmp_path / 'audio', Settings())
    else:
        assert await extract(tmp_path / 'audio', Settings()) == result
    assert all(child.returncode is not None for child in children)


async def test_delete_member_revokes_templates_and_retries_committed_file_cleanup(setup, monkeypatch):
    settings, sessions, users, c = setup
    member = users['employee'].id
    assert (await enroll(c['admin'], member)).status_code == 202
    await process_once(sessions, settings, extractor=fake_extract)
    preview = await c['admin'].get('/api/v1/members/' + member + '/deletion')
    assert preview.json() == {'voiceprints': 1, 'recordings': 1}
    original_unlink = Path.unlink
    def denied(path, *args, **kwargs):
        if path.parent == settings.media_dir / 'voiceprints':
            raise PermissionError('controlled')
        return original_unlink(path, *args, **kwargs)
    with patch.object(Path, 'unlink', denied):
        response = await c['admin'].delete('/api/v1/members/' + member)
        assert response.status_code == 200 and response.json()['cleanupPending'] == 1
        state = (await c['admin'].get('/api/v1/settings/voiceprints/cleanup')).json()
        assert state == {'legacy': {'members': 0, 'voiceprints': 0, 'recordings': 0}, 'pending': 1, 'failed': 1}
    async with sessions() as db:
        assert await db.scalar(select(Voiceprint).where(Voiceprint.member_id == member)) is None
        assert await db.scalar(select(VoiceprintCleanup).where(VoiceprintCleanup.member_id == member))
    await drain(sessions, settings)  # A new worker transaction recovers the intent.
    assert not list((settings.media_dir / 'voiceprints').iterdir())
    assert (await c['admin'].post('/api/v1/settings/voiceprints/cleanup')).json()['pending'] == 0


async def test_legacy_cleanup_is_explicit_company_scoped_and_disable_preserves(setup):
    settings, sessions, users, c = setup
    for key in ('employee', 'peer'):
        await enroll(c['admin'], users[key].id)
        await process_once(sessions, settings, extractor=fake_extract)
    await c['admin'].patch('/api/v1/members/' + users['peer'].id, json={'active': False})
    async with sessions.begin() as db:
        old = await db.get(Member, users['employee'].id)
        old.deleted, old.active = True, False
    await drain(sessions, settings)
    preview = (await c['admin'].get('/api/v1/settings/voiceprints/cleanup')).json()
    assert preview['legacy'] == {'members': 1, 'voiceprints': 1, 'recordings': 1}
    for key in ('employee', 'outsider'):
        assert (await c[key].post('/api/v1/settings/voiceprints/cleanup')).status_code in (401, 403)
    result = await c['admin'].post('/api/v1/settings/voiceprints/cleanup')
    assert result.status_code == 200 and result.json()['legacy']['members'] == 0
    async with sessions() as db:
        assert await db.scalar(select(Voiceprint).where(Voiceprint.member_id == users['peer'].id))
    assert len(list((settings.media_dir / 'voiceprints').iterdir())) == 1


async def test_deletion_rollback_does_not_remove_audio_and_inflight_is_cancelled(setup):
    settings, sessions, users, c = setup
    member = users['employee'].id
    await enroll(c['admin'], member)
    async with sessions() as db:
        item = await db.scalar(select(Voiceprint).where(Voiceprint.member_id == member))
        await remove_enrollment(db, item)
        await db.rollback()
    await drain(sessions, settings)
    assert len(list((settings.media_dir / 'voiceprints').iterdir())) == 1
    started, cancelled = asyncio.Event(), asyncio.Event()
    async def slow(*args):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    task = asyncio.create_task(process_once(sessions, settings, extractor=slow))
    await asyncio.wait_for(started.wait(), 5)
    assert (await c['admin'].delete('/api/v1/members/' + member)).status_code == 200
    assert await asyncio.wait_for(task, 5)
    assert cancelled.is_set()
    async with sessions() as db:
        assert not await db.scalar(select(Voiceprint.id).where(Voiceprint.member_id == member))
