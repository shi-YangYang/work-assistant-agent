"""Browser-approved, PKCE-bound sessions used only by the desktop API."""
import base64
from datetime import timedelta
import hashlib
import secrets

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select

from .authentication import digest, throttle
from .business_access import company_lock
from .models import Company, DesktopAuthorization, DesktopSession, Member, Session, now
from .service import problem

# These exact native-client paths accept requests without a browser Origin.
NATIVE_WRITES = {'/api/v1/desktop/login/start', '/api/v1/desktop/login/exchange', '/api/v1/desktop/logout'}


class Start(BaseModel):
    model_config = ConfigDict(extra='forbid')
    challenge: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$')


class Exchange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$')
    verifier: str = Field(min_length=43, max_length=128, pattern=r'^[A-Za-z0-9._~-]+$')


class Approval(BaseModel):
    model_config = ConfigDict(extra='forbid')
    approve: bool


def identity_dto(actor, company, expires):
    return {'member': {'id': actor.id, 'name': actor.name, 'role': actor.role},
            'company': {'id': company.id, 'name': company.name}, 'expiresAt': expires.isoformat()}


def register_routes(app, AUTH, DB, settings, sessions):
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

    DESKTOP = Depends(native_identity)

    @app.get('/api/v1/desktop/info')
    async def info():
        return {'protocolVersion': 1, 'webOrigin': settings.web_origin}

    async def start_rate(request: Request):
        async with sessions.begin() as db:
            await throttle(db, 'desktop-start:' + (request.client.host if request.client else 'unknown'), limit=60)
            await db.execute(delete(DesktopAuthorization).where(DesktopAuthorization.expires_at < now() - timedelta(days=1)))

    @app.post('/api/v1/desktop/login/start')
    async def start(body: Start, limited=Depends(start_rate), db=DB):
        identifier = secrets.token_urlsafe(32)
        expires = now() + timedelta(minutes=5)
        db.add(DesktopAuthorization(request_hash=digest(identifier), challenge=body.challenge, expires_at=expires))
        return {'requestId': identifier, 'expiresAt': expires.isoformat(), 'authorizationUrl': settings.web_origin + '/desktop/connect?request=' + identifier}

    async def grant(db, identifier, *, lock=False):
        if len(identifier) != 43:
            problem(410, '授权已失效，请回到桌面重新连接', 'invalid_grant')
        query = select(DesktopAuthorization).where(DesktopAuthorization.request_hash == digest(identifier))
        item = await db.scalar(query.with_for_update().execution_options(populate_existing=True) if lock else query)
        if item is None or item.expires_at <= now() or item.state in ('denied', 'consumed'):
            problem(410, '授权已失效，请回到桌面重新连接', 'invalid_grant')
        return item

    @app.get('/api/v1/auth/desktop/requests/{identifier}')
    async def preview(identifier: str, actor=AUTH, db=DB):
        item = await grant(db, identifier)
        return {'state': item.state, 'expiresAt': item.expires_at.isoformat(), 'companyName': (await db.get(Company, actor.company_id)).name}

    @app.post('/api/v1/auth/desktop/requests/{identifier}')
    async def approve(identifier: str, body: Approval, request: Request, actor=AUTH, db=DB):
        item = await grant(db, identifier, lock=True)
        if item.state != 'pending':
            problem(409, '此授权请求已经处理，请回到桌面继续')
        item.state = 'approved' if body.approve else 'denied'
        item.member_id, item.company_id, item.session_id = actor.id, actor.company_id, request.state.session.id
        return {'ok': True}

    @app.post('/api/v1/desktop/login/exchange')
    async def exchange(body: Exchange, db=DB):
        # Lock order matches browser approval/revocation: company then grant.
        candidate = await grant(db, body.requestId)
        if candidate.company_id:
            await company_lock(db, candidate.company_id)
        item = await grant(db, body.requestId, lock=True)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(body.verifier.encode()).digest()).decode().rstrip('=')
        if not secrets.compare_digest(challenge, item.challenge):
            problem(403, '授权校验失败，请回到桌面重新连接', 'invalid_grant')
        # Server-side bound on exchange frequency, without consuming the grant.
        if item.polled_at and (now() - item.polled_at).total_seconds() < 1:
            return JSONResponse({'error': {'code': 'slow_down', 'message': '请稍后继续授权'}}, status_code=429, headers={'Retry-After': '2'})
        item.polled_at = now()
        if item.state == 'pending':
            return JSONResponse({'state': 'pending'}, status_code=202)
        session = await db.get(Session, item.session_id)
        actor = await db.get(Member, item.member_id)
        if not session or session.expires_at <= now() or not actor or not actor.active or actor.company_id != item.company_id:
            problem(410, '账号授权已失效，请重新登录', 'invalid_grant')
        token, expires = secrets.token_urlsafe(48), session.expires_at
        db.add(DesktopSession(company_id=actor.company_id, member_id=actor.id, session_id=session.id, token_hash=digest(token), expires_at=expires))
        item.state = 'consumed'
        return {'token': token, **identity_dto(actor, await db.get(Company, actor.company_id), expires)}

    @app.get('/api/v1/desktop/me')
    async def me(request: Request, actor=DESKTOP, db=DB):
        return identity_dto(actor, await db.get(Company, actor.company_id), request.state.desktop_session.expires_at)

    @app.post('/api/v1/desktop/logout')
    async def logout(request: Request, actor=DESKTOP, db=DB):
        await db.delete(request.state.desktop_session)
        return {'ok': True}

    return DESKTOP
