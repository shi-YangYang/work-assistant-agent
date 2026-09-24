import hashlib
import secrets
from datetime import timedelta
from paa_server.core.errors import problem
from paa_server.db.base import now
from paa_server.modules.auth.models import DingTalkAuthorization, LoginAttempt, Session
from pwdlib import PasswordHash
from sqlalchemy import delete, func, select, update
from starlette.concurrency import run_in_threadpool

passwords = PasswordHash.recommended()


DUMMY_PASSWORD = passwords.hash('constant-not-a-login-password')


COOKIE = 'paa_company_session'


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


async def verify_password(value, stored):
    valid = await run_in_threadpool(passwords.verify, value, stored or DUMMY_PASSWORD)
    return bool(stored) and valid


def issue_session(db, actor, response, settings):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db.add(Session(member_id=actor.id, token_hash=digest(token), csrf=csrf, expires_at=now() + timedelta(hours=8)))
    response.set_cookie(COOKIE, token, httponly=True, secure=settings.cookie_secure, samesite='lax', max_age=8*3600, path='/')
    return csrf


async def revoke_member(db, member_id):
    await db.execute(delete(Session).where(Session.member_id == member_id))
    await db.execute(update(DingTalkAuthorization).where(DingTalkAuthorization.member_id == member_id).values(revoked=True, proof_hash=None))


async def throttle(db, identity, *, limit=12):
    key = digest(identity)
    recent = now() - timedelta(minutes=10)
    # Count and insert atomically across concurrent requests without a company lock.
    from sqlalchemy import text
    await db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'), {'key': key})
    count = await db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.identity == key, LoginAttempt.created_at > recent))
    if count >= limit:
        problem(429, '尝试次数过多，请 10 分钟后重试')
    db.add(LoginAttempt(identity=key))
    await db.flush()


async def limit_authenticated_request(sessions, request, namespace):
    # Called as a dependency BEFORE identity takes the company lock. This short
    # transaction commits failure attempts without borrowing a second connection
    # while the request holds its business transaction (pool size is only 3).
    async with sessions.begin() as db:
        token = request.cookies.get(COOKIE, '')
        session = await db.scalar(select(Session).where(Session.token_hash == digest(token), Session.expires_at > now())) if token else None
        key = session.member_id if session else (request.client.host if request.client else 'unknown')
        await throttle(db, namespace + ':' + key)
