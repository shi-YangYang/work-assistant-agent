import asyncio
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.db.base import now
from app.modules.auth.models import DingTalkIdentity, Session
from app.modules.members.cleanup_inactive import cleanup_inactive_members
from app.modules.members.models import Member
from app.modules.messages.models import Message
from app.modules.reports.models import ReportObligation, ReportNotification
from app.modules.voiceprints.models import Voiceprint, VoiceprintCleanup
from app.security.locks import company_lock
from app.tasks.models import Job
from _support.work.search_metrics_feedback import content, work
from _support.work.team_workspace import DAY, report

pytestmark = pytest.mark.asyncio


async def deactivate(sessions, *members):
    async with sessions.begin() as db:
        for member in members:
            (await db.get(Member, member.id)).active = False


async def test_cleanup_reuses_deletion_preserves_history_and_is_company_scoped(setup):
    settings, sessions, users, clients = setup
    employee = users['employee']
    async with sessions.begin() as db:
        task = await work(db, employee, content('保留历史'), DAY)
        submitted = await report(db, employee, '2026-09-12')
        message = Message(company_id=employee.company_id, owner_id=employee.id, text='原始记录')
        db.add(message)
        await db.flush()
        job = Job(company_id=employee.company_id, owner_id=employee.id, kind='message', target_id=message.id, state='running', fence=2, lease_until=now() + timedelta(minutes=1))
        obligation = ReportObligation(company_id=employee.company_id, owner_id=employee.id, kind='daily', period='2026-09-13', period_end='2026-09-13', timezone='Asia/Shanghai', rule_revision=1, generate_at=now(), deadline_at=now(), reminders=True, before_minutes=0)
        db.add_all([job, obligation, DingTalkIdentity(company_id=employee.company_id, member_id=employee.id, corp_id='corp', client_id='client', user_id=uuid4().hex, union_id=uuid4().hex)])
        inactive_admin = Member(company_id=employee.company_id, username='admin_' + uuid4().hex, name='历史管理员', role='admin', active=False)
        already_deleted = Member(company_id=employee.company_id, username='old_' + uuid4().hex, name='已删除', active=False, deleted=True)
        db.add_all([inactive_admin, already_deleted])
        await db.flush()
        db.add(ReportNotification(company_id=employee.company_id, owner_id=employee.id, obligation_id=obligation.id, stage='ready'))
    await deactivate(sessions, employee, users['outsider'])
    assert (await clients['employee'].get('/api/v1/auth/me')).status_code == 401
    # Leave its historical session for cleanup to revoke rather than relying on auth reads.
    async with sessions.begin() as db:
        db.add(Session(member_id=employee.id, token_hash=uuid4().hex, csrf=uuid4().hex, expires_at=now() + timedelta(hours=1)))
    result = await cleanup_inactive_members(sessions, settings, company_ids=[employee.company_id])
    assert result == {'deleted': 1, 'skipped': 0, 'failed': 0, 'remaining': 0, 'cleanupPending': 0, 'cleanupFailed': 0, 'cleanupErrors': 0, 'failures': []}
    async with sessions() as db:
        stored = await db.get(Member, employee.id)
        assert stored.deleted and not stored.active and stored.password_hash is None
        assert stored.username == 'deleted:' + employee.id
        assert not (await db.get(Member, users['peer'].id)).deleted
        assert not (await db.get(Member, users['outsider'].id)).deleted
        assert not (await db.get(Member, inactive_admin.id)).deleted
        assert (await db.get(Member, already_deleted.id)).username == already_deleted.username
        assert not await db.scalar(select(Session.id).where(Session.member_id == employee.id))
        assert not await db.scalar(select(DingTalkIdentity.id).where(DingTalkIdentity.member_id == employee.id))
        assert (await db.get(Job, job.id)).state == 'cancelled'
        assert (await db.get(Job, job.id)).fence == 3
        assert (await db.get(ReportObligation, obligation.id)).state == 'cancelled'
        assert not await db.scalar(select(ReportNotification.id).where(ReportNotification.owner_id == employee.id))
        assert not (await db.get(Message, message.id)).deleted
    for path in ('/work-items/' + task.id, '/reports/' + submitted.id):
        assert (await clients['admin'].get('/api/v1' + path)).status_code == 200
    recreated = await clients['admin'].post('/api/v1/members', json={'username': employee.username, 'name': '新账号', 'password': '1111'})
    assert recreated.status_code == 201 and recreated.json()['id'] != employee.id
    assert (await cleanup_inactive_members(sessions, settings, company_ids=[employee.company_id]))['deleted'] == 0
    other = await cleanup_inactive_members(sessions, settings, company_ids=[users['outsider'].company_id])
    assert other['deleted'] == 1


@pytest.mark.parametrize('interrupt', [False, True])
async def test_cleanup_rolls_back_failed_member_and_can_resume_after_interruption(setup, monkeypatch, interrupt):
    from app.modules.members import cleanup_inactive as cleanup
    settings, sessions, users, _ = setup
    await deactivate(sessions, users['employee'], users['peer'])
    original = cleanup.delete_member_command
    visited = []
    class Interrupted(BaseException):
        pass
    async def interrupted(identifier, actor, db):
        visited.append(identifier)
        await original(identifier, actor, db)
        if len(visited) == 2:
            raise Interrupted() if interrupt else RuntimeError('controlled')
    monkeypatch.setattr(cleanup, 'delete_member_command', interrupted)
    if interrupt:
        with pytest.raises(Interrupted):
            await cleanup_inactive_members(sessions, settings, company_ids=[users['admin'].company_id])
    else:
        result = await cleanup_inactive_members(sessions, settings, company_ids=[users['admin'].company_id])
        assert result['deleted'] == result['failed'] == result['remaining'] == 1
        assert result['failures'][0]['memberId'] == visited[1]
    async with sessions() as db:
        assert (await db.get(Member, visited[0])).deleted
        assert not (await db.get(Member, visited[1])).deleted
    monkeypatch.setattr(cleanup, 'delete_member_command', original)
    result = await cleanup_inactive_members(sessions, settings, company_ids=[users['admin'].company_id])
    assert result['deleted'] == 1 and result['failed'] == result['remaining'] == 0


async def test_cleanup_rechecks_candidate_state_under_lock(setup, monkeypatch):
    from app.modules.members import cleanup_inactive as cleanup
    settings, sessions, users, _ = setup
    await deactivate(sessions, users['employee'], users['peer'])
    original = cleanup.delete_member_command
    async def changed(identifier, actor, db):
        await original(identifier, actor, db)
        other = users['peer'] if identifier == users['employee'].id else users['employee']
        (await db.get(Member, other.id)).active = True
    monkeypatch.setattr(cleanup, 'delete_member_command', changed)
    result = await cleanup_inactive_members(sessions, settings, company_ids=[users['admin'].company_id])
    assert result['deleted'] == result['skipped'] == 1 and result['remaining'] == 0


async def test_cleanup_waits_for_company_business_lock_and_rechecks_candidate(setup, monkeypatch):
    from app.modules.members import cleanup_inactive as cleanup
    settings, sessions, users, _ = setup
    employee = users['employee']
    await deactivate(sessions, employee)
    waiting = asyncio.Event()
    cleanup_pid = None

    async def observe_lock(db, company_id):
        nonlocal cleanup_pid
        cleanup_pid = await db.scalar(text('SELECT pg_backend_pid()'))
        waiting.set()
        await company_lock(db, company_id)

    monkeypatch.setattr(cleanup, 'company_lock', observe_lock)
    task = None
    try:
        async with sessions.begin() as blocker:
            await company_lock(blocker, employee.company_id, shared=True)
            blocker_pid = await blocker.scalar(text('SELECT pg_backend_pid()'))
            task = asyncio.create_task(cleanup_inactive_members(sessions, settings, company_ids=[employee.company_id]))
            async with asyncio.timeout(5):
                await waiting.wait()
                # Observe PostgreSQL blocking, rather than assume the task reached
                # its lock after an arbitrary sleep. No member row is locked yet.
                while not await blocker.scalar(text('''
                    SELECT EXISTS (
                        SELECT 1 FROM pg_locks
                        WHERE pid = :cleanup_pid AND locktype = 'advisory'
                          AND mode = 'ExclusiveLock' AND NOT granted
                          AND :blocker_pid = ANY(pg_blocking_pids(pid))
                    )
                '''), {'cleanup_pid': cleanup_pid, 'blocker_pid': blocker_pid}):
                    assert not task.done(), 'Cleanup bypassed the company business lock'
                assert not task.done()
                # Simulate a legacy state correction committing while cleanup
                # waits; the stale candidate must not be deleted after release.
                (await blocker.get(Member, employee.id)).active = True
        result = await asyncio.wait_for(task, 5)
    finally:
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert result['skipped'] == 1
    assert result['deleted'] == result['failed'] == result['remaining'] == 0
    async with sessions() as db:
        stored = await db.get(Member, employee.id)
        assert stored.active and not stored.deleted
        assert stored.username == employee.username and stored.password_hash == employee.password_hash


async def test_cleanup_file_failure_survives_and_retries_without_deleting_account_twice(setup, monkeypatch):
    settings, sessions, users, _ = setup
    employee = users['employee']
    filename = str(uuid4())
    folder = settings.media_dir / 'voiceprints'
    folder.mkdir(parents=True, exist_ok=True)
    file = folder / filename
    file.write_bytes(b'controlled recording')
    async with sessions.begin() as db:
        (await db.get(Member, employee.id)).active = False
        db.add(Voiceprint(company_id=employee.company_id, member_id=employee.id, consent_by=users['admin'].id, ready_path=filename, state='ready'))
    original = Path.unlink
    def denied(path, *args, **kwargs):
        if path == file:
            raise PermissionError('controlled')
        return original(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'unlink', denied)
        result = await cleanup_inactive_members(sessions, settings, company_ids=[employee.company_id])
    assert result['deleted'] == result['cleanupPending'] == result['cleanupFailed'] == 1
    async with sessions() as db:
        assert await db.scalar(select(Voiceprint).where(Voiceprint.member_id == employee.id)) is None
        assert await db.scalar(select(VoiceprintCleanup).where(VoiceprintCleanup.member_id == employee.id))
    result = await cleanup_inactive_members(sessions, settings, company_ids=[employee.company_id])
    assert result['deleted'] == result['cleanupPending'] == result['cleanupFailed'] == 0
    assert not file.exists()


async def test_cleanup_drain_failure_preserves_committed_results_and_continues_other_companies(setup, monkeypatch):
    from app.modules.members import cleanup_inactive as cleanup
    settings, sessions, users, _ = setup
    await deactivate(sessions, users['employee'], users['outsider'])
    original = cleanup.drain
    visited = []
    async def failed(sessions, settings, *, company_id):
        visited.append(company_id)
        if company_id == users['employee'].company_id:
            raise RuntimeError('controlled drain transaction failure')
        await original(sessions, settings, company_id=company_id)
    monkeypatch.setattr(cleanup, 'drain', failed)
    scope = [users['employee'].company_id, users['outsider'].company_id]
    result = await cleanup_inactive_members(sessions, settings, company_ids=scope)
    assert set(visited) == set(scope)
    assert result['deleted'] == 2 and result['remaining'] == 0 and result['cleanupErrors'] == 1
    assert result['failures'][0]['companyId'] == users['employee'].company_id
