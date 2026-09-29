"""Opt-in SIGKILL + actual 90-second lease expiry; no provider or fake clock."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
from sqlalchemy import func, select

from app.db.idempotency import Idempotency
from app.modules.messages.models import Message
from app.modules.work.models import WorkItem
from app.tasks.models import Job

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.getenv('SPEC044_PROCESS_RECOVERY') != '1', reason='Opt-in process fault test; 90-second real lease expiry')]


async def test_owned_worker_sigkill_before_write_after_commit_and_after_delivery(setup, tmp_path):
    settings, sessions, users, _ = setup
    boundaries = ('before_write', 'after_write', 'after_delivery')
    jobs = {}
    async with sessions.begin() as db:
        for role, boundary in zip(('admin', 'employee', 'peer'), boundaries):
            actor = users[role]
            source = Message(company_id=actor.company_id, owner_id=actor.id, text='固定恢复输入 ' + boundary)
            db.add(source)
            await db.flush()
            job = Job(company_id=actor.company_id, owner_id=actor.id, target_id=source.id, kind='message')
            db.add(job)
            await db.flush()
            jobs[job.id] = boundary
    markers = tmp_path / 'markers'
    markers.mkdir()
    control = tmp_path / 'control.json'
    control.write_text(json.dumps({'markers': str(markers), 'jobs': jobs}))
    control.chmod(0o600)
    environment = {**os.environ, 'DATABASE_URL': settings.database_url, 'PAA_MEDIA_DIR': str(settings.media_dir), 'PAA_MODEL_KEY_FILE': str(settings.model_key_file), 'PAA_WORKER_CONCURRENCY': '3'}
    script = Path(__file__).with_name('full_system_worker_probe.py')
    logfile = (tmp_path / 'worker.log').open('w')
    process = subprocess.Popen([sys.executable, str(script), str(control), 'crash'], env=environment, stdout=logfile, stderr=subprocess.STDOUT)
    recovery = None
    started = time.monotonic()
    result = {'mode': 'production run_slots/claim + deterministic business command; real OS SIGKILL and real lease time', 'boundaries': list(boundaries)}
    try:
        for _ in range(200):
            assert process.poll() is None, (tmp_path / 'worker.log').read_text()
            if {path.name for path in markers.iterdir()} == set(jobs):
                break
            await asyncio.sleep(.1)
        else:
            pytest.fail('Owned worker did not reach all three controlled barriers')
        async with sessions() as db:
            before = (await db.scalars(select(Job).where(Job.id.in_(jobs)))).all()
            assert sorted(row.state for row in before) == ['running', 'running', 'succeeded']
            assert await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id.in_([users[role].id for role in ('admin', 'employee', 'peer')]))) == 2
            leases = [row.lease_until for row in before if row.lease_until]
            fences = {row.id: row.fence for row in before}
        process.kill()
        await asyncio.to_thread(process.wait, timeout=5)
        assert process.returncode < 0
        result['killedPid'] = process.pid
        # Start immediately: production claim must not steal an unexpired lease.
        recovery = subprocess.Popen([sys.executable, str(script), str(control), 'recover'], env=environment, stdout=logfile, stderr=subprocess.STDOUT)
        await asyncio.sleep(1)
        async with sessions() as db:
            live = (await db.scalars(select(Job).where(Job.id.in_(jobs)))).all()
            assert {row.id: row.fence for row in live} == fences
        await asyncio.wait_for(asyncio.to_thread(recovery.wait, timeout=125), 130)
        assert recovery.returncode == 0, (tmp_path / 'worker.log').read_text()
        assert datetime.now(timezone.utc) >= max(leases)
        async with sessions() as db:
            after = (await db.scalars(select(Job).where(Job.id.in_(jobs)))).all()
            assert {row.state for row in after} == {'succeeded'}
            assert all(row.lease_until is None for row in after)
            for row in after:
                assert row.fence == fences[row.id] + (0 if jobs[row.id] == 'after_delivery' else 2)
                assert (await db.get(WorkItem, row.result['workId'])).title == '恢复唯一工作 ' + jobs[row.id]
            assert await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id.in_([users[role].id for role in ('admin', 'employee', 'peer')]))) == 3
            assert await db.scalar(select(func.count()).select_from(Idempotency).where(Idempotency.key.in_(jobs))) == 3
        result.update(status='PASS', elapsedSeconds=round(time.monotonic() - started, 2), finalWorks=3, finalReceipts=3, stolenUnexpiredLeases=0, duplicateWrites=0)
        directory = os.getenv('SPEC044_SERVER_EVIDENCE')
        if directory:
            path = Path(directory) / 'process-worker-recovery.json'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, indent=2) + '\n')
    finally:
        for child in (process, recovery):
            if child and child.poll() is None:
                child.kill()
                await asyncio.to_thread(child.wait, timeout=5)
        logfile.close()
