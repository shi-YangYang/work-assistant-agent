import hashlib
import secrets
from fastapi import Depends, Request
from paa_server.core.errors import problem
from paa_server.db.base import now
from paa_server.modules.auth.models import Session
from paa_server.modules.auth.sessions import COOKIE
from paa_server.modules.members.models import Member
from paa_server.security.locks import company_lock as business_company_lock
from sqlalchemy import select


async def db_dep(request: Request):
    async with request.app.state.sessions() as db:
        try:
            yield db
            await db.commit()
        except BaseException:
            await db.rollback()
            raise

DB = Depends(db_dep, scope='function')


async def identity(request: Request, db=DB):
    raw = request.cookies.get(COOKIE, '')
    if not raw:
        problem(401, '请先登录', 'login_required')
    session = await db.scalar(select(Session).where(Session.token_hash == hashlib.sha256(raw.encode()).hexdigest(), Session.expires_at > now()))
    actor = await db.get(Member, session.member_id) if session else None
    if actor is not None:
        # Model probes and uploads can wait on network/decoders; they use
        # their own final authorization checks rather than holding this lock.
        long_operation = request.url.path in ('/api/v1/settings/model-services/models', '/api/v1/settings/model-services/test', '/api/v1/uploads') and request.method == 'POST'
        long_operation = long_operation or request.url.path.endswith(('/events', '/feedback')) or (request.url.path.startswith('/api/v1/uploads/') and request.url.path.endswith('/preview'))
        if not long_operation:
            await business_company_lock(db, actor.company_id)
            session = await db.scalar(select(Session).where(Session.id == session.id, Session.expires_at > now()).execution_options(populate_existing=True))
        actor = await db.scalar(select(Member).where(Member.id == actor.id).execution_options(populate_existing=True))
    if actor is None or not actor.active or session is None:
        problem(401, '登录已过期，请重新登录', 'login_required')
    if request.method not in ('GET', 'HEAD') and not secrets.compare_digest(request.headers.get('x-csrf-token', ''), session.csrf):
        problem(403, '请求校验失败，请刷新后重试', 'csrf_rejected')
    request.state.session = session
    return actor

AUTH = Depends(identity)


async def admin(actor=AUTH):
    if actor.role != 'admin':
        problem(403, '仅老板／管理员可进行此操作')
    return actor

ADMIN = Depends(admin)


def get_settings(request: Request):
    return request.app.state.settings


def get_sessions(request: Request):
    return request.app.state.sessions


SETTINGS = Depends(get_settings)
SESSIONS = Depends(get_sessions)
