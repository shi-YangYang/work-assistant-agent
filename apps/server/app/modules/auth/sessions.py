import hashlib
import secrets
from datetime import timedelta
from app.core.errors import problem
from app.db.base import now
from app.modules.auth.models import DingTalkAuthorization, LoginAttempt, Session
from app.modules.auth.session_policy import ABSOLUTE_LIFETIME, deadline, renewal_due
from app.modules.members.models import Member
from app.security.locks import company_lock
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
    instant = now()
    expires = deadline(instant, instant)
    db.add(Session(member_id=actor.id, token_hash=digest(token), csrf=csrf, created_at=instant, expires_at=expires))
    set_session_cookie(response, token, expires, settings, instant=instant)
    return csrf


def set_session_cookie(response, token, expires_at, settings, *, instant=None):
    instant = instant or now()
    seconds = int((expires_at - instant).total_seconds())
    if seconds > 0:
        response.set_cookie(COOKIE, token, httponly=True, secure=settings.cookie_secure, samesite='lax', max_age=seconds, path='/')


def live_session(instant):
    return (Session.expires_at > instant, Session.created_at > instant - ABSOLUTE_LIFETIME)


async def renew_session(sessions, original):
    # The business transaction has already committed and released its connection.
    # Company -> member/session matches logout, password changes and disable.
    async with sessions.begin() as db:
        actor = await db.get(Member, original.member_id)
        if actor is None:
            return None
        company_id = actor.company_id
        await company_lock(db, company_id)
        actor = await db.scalar(select(Member).where(Member.id == original.member_id).execution_options(populate_existing=True))
        instant = now()
        current = await db.scalar(select(Session).where(
            Session.id == original.id, Session.member_id == original.member_id,
            Session.token_hash == original.token_hash, *live_session(instant),
        ))
        if actor is None or not actor.active or actor.company_id != company_id or current is None:
            return None
        expires = current.expires_at
        if renewal_due(current.created_at, expires, instant):
            expires = await db.scalar(update(Session).where(
                Session.id == current.id, Session.member_id == actor.id,
                Session.token_hash == original.token_hash, *live_session(instant),
                Session.created_at == current.created_at,
                Session.expires_at == current.expires_at,
                Session.expires_at < deadline(current.created_at, instant),
            ).values(expires_at=deadline(current.created_at, instant)).returning(Session.expires_at))
    # Return only after commit. A failed commit never authorizes a longer cookie.
    return expires


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
        session = await db.scalar(select(Session).where(Session.token_hash == digest(token), *live_session(now()))) if token else None
        key = session.member_id if session else (request.client.host if request.client else 'unknown')
        await throttle(db, namespace + ':' + key)
