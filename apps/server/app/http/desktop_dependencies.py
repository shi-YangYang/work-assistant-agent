from datetime import timedelta
from fastapi import Depends, Request
from app.core.errors import problem
from app.db.base import now
from app.http.dependencies import DB
from app.modules.auth.models import DesktopAuthorization, DesktopSession
from app.modules.auth.sessions import digest, throttle
from app.modules.members.models import Member
from app.security.locks import company_lock
from sqlalchemy import delete, select


async def native_identity(request: Request, db=DB):
    raw = request.headers.get('authorization', '')
    if not raw.startswith('Bearer ') or len(raw) > 200:
        problem(401, '请重新连接公司账号', 'desktop_login_required')
    record = await db.scalar(select(DesktopSession).where(DesktopSession.token_hash == digest(raw[7:]), DesktopSession.expires_at > now()))
    if record is None:
        problem(401, '公司登录已过期，请重新登录', 'desktop_login_required')
    await company_lock(db, record.company_id)
    record = await db.scalar(select(DesktopSession).where(DesktopSession.id == record.id, DesktopSession.expires_at > now()).execution_options(populate_existing=True))
    actor = await db.get(Member, record.member_id) if record else None
    if actor is None or not actor.active or actor.company_id != record.company_id:
        problem(401, '公司登录已失效，请重新登录', 'desktop_login_required')
    request.state.desktop_session = record
    return actor


async def start_rate(request: Request):
    async with request.app.state.sessions.begin() as db:
        await throttle(db, 'desktop-start:' + (request.client.host if request.client else 'unknown'), limit=60)
        await db.execute(delete(DesktopAuthorization).where(DesktopAuthorization.expires_at < now() - timedelta(days=1)))


DESKTOP = Depends(native_identity)
