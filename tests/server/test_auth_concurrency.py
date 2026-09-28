import asyncio
import hashlib

import pytest
from sqlalchemy import func, select

from app.modules.auth.models import LoginAttempt
from app.modules.members.models import Member
from app.security.locks import company_lock

pytestmark = pytest.mark.asyncio


async def test_parallel_login_cannot_share_seventh_failure_or_queue_hashes(setup, monkeypatch):
    _, sessions, users, c = setup
    user = users['employee']
    identity = hashlib.sha256(f'127.0.0.1:{user.username}'.encode()).hexdigest()
    async with sessions.begin() as db:
        db.add_all(LoginAttempt(identity=identity) for _ in range(7))
    entered, release = asyncio.Event(), asyncio.Event()
    count = 0
    async def verify(*args):
        nonlocal count
        count += 1
        entered.set()
        await release.wait()
        return False
    monkeypatch.setattr('app.modules.auth.router.verify_password', verify)
    payload = {'username': user.username, 'password': 'bad-password'}
    first = asyncio.create_task(c['employee'].post('/api/v1/auth/login', json=payload))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        results = await asyncio.gather(*(c['employee'].post('/api/v1/auth/login', json=payload) for _ in range(5)))
        assert [r.status_code for r in results] == [429] * 5
    finally:
        release.set()
    assert (await first).status_code == 401 and count == 1
    assert (await c['employee'].post('/api/v1/auth/login', json=payload)).status_code == 429
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.identity == identity)) == 8


async def test_login_success_clears_failures_and_disable_during_hash_still_blocks(setup, monkeypatch):
    _, sessions, users, c = setup
    payload = {'username': users['employee'].username, 'password': 'controlled-test-password'}
    identity = hashlib.sha256(f"127.0.0.1:{payload['username']}".encode()).hexdigest()
    async with sessions.begin() as db:
        db.add_all(LoginAttempt(identity=identity) for _ in range(7))
    assert (await c['employee'].post('/api/v1/auth/login', json=payload)).status_code == 200
    async with sessions() as db:
        assert not await db.scalar(select(LoginAttempt.id).where(LoginAttempt.identity == identity))
    async def disable(*args):
        async with sessions.begin() as db:
            await company_lock(db, users['employee'].company_id)
            (await db.get(Member, users['employee'].id)).active = False
        return True
    monkeypatch.setattr('app.modules.auth.router.verify_password', disable)
    assert (await c['employee'].post('/api/v1/auth/login', json=payload)).status_code == 401


async def test_shared_reads_parallel_writer_waits_and_cannot_upgrade(setup):
    _, sessions, users, _ = setup
    company = users['admin'].company_id
    acquired = asyncio.Event()
    async with sessions.begin() as first:
        await company_lock(first, company, shared=True)
        async with sessions.begin() as second:
            await asyncio.wait_for(company_lock(second, company, shared=True), 2)
            with pytest.raises(RuntimeError, match='cannot upgrade'):
                await company_lock(second, company)
        async def writer():
            async with sessions.begin() as db:
                await company_lock(db, company)
                acquired.set()
        task = asyncio.create_task(writer())
        await asyncio.sleep(.05)
        assert not acquired.is_set()
    await asyncio.wait_for(task, 2)
    assert acquired.is_set()


async def test_read_endpoint_rechecks_revocation_after_waiting_for_writer(setup):
    _, sessions, users, c = setup
    from app.modules.auth.sessions import revoke_member
    async with sessions.begin() as db:
        await company_lock(db, users['admin'].company_id)
        request = asyncio.create_task(c['admin'].get('/api/v1/settings/model-usage'))
        await asyncio.sleep(.05)
        assert not request.done()
        await revoke_member(db, users['admin'].id)
    assert (await asyncio.wait_for(request, 2)).status_code == 401


async def test_nested_rollback_does_not_cache_released_write_lock(setup):
    _, sessions, users, _ = setup
    company = users['admin'].company_id
    async with sessions.begin() as first:
        nested = await first.begin_nested()
        await company_lock(first, company)
        await nested.rollback()
        async with sessions.begin() as second:
            await company_lock(second, company)
            reacquired = asyncio.create_task(company_lock(first, company))
            await asyncio.sleep(.05)
            assert not reacquired.done()
        await asyncio.wait_for(reacquired, 2)
