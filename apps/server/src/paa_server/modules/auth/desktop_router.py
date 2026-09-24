import base64
import hashlib
import secrets
from datetime import timedelta
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from paa_server.core.errors import problem
from paa_server.db.base import now
from paa_server.http.dependencies import AUTH, DB, SETTINGS
from paa_server.http.desktop_dependencies import DESKTOP, start_rate
from paa_server.modules.auth.desktop import Approval, Exchange, Start, grant, identity_dto
from paa_server.modules.auth.models import DesktopAuthorization, DesktopSession, Session
from paa_server.modules.auth.sessions import digest
from paa_server.modules.members.models import Company, Member
from paa_server.security.locks import company_lock

router = APIRouter()


@router.get('/api/v1/desktop/info')
async def info(settings=SETTINGS):
    return {'protocolVersion': 1, 'webOrigin': settings.web_origin}


@router.post('/api/v1/desktop/login/start')
async def start(body: Start, limited=Depends(start_rate), db=DB, settings=SETTINGS):
    identifier = secrets.token_urlsafe(32)
    expires = now() + timedelta(minutes=5)
    db.add(DesktopAuthorization(request_hash=digest(identifier), challenge=body.challenge, expires_at=expires))
    return {'requestId': identifier, 'expiresAt': expires.isoformat(), 'authorizationUrl': settings.web_origin + '/desktop/connect?request=' + identifier}


@router.get('/api/v1/auth/desktop/requests/{identifier}')
async def preview(identifier: str, actor=AUTH, db=DB):
    item = await grant(db, identifier)
    return {'state': item.state, 'expiresAt': item.expires_at.isoformat(), 'companyName': (await db.get(Company, actor.company_id)).name}


@router.post('/api/v1/auth/desktop/requests/{identifier}')
async def approve(identifier: str, body: Approval, request: Request, actor=AUTH, db=DB):
    item = await grant(db, identifier, lock=True)
    if item.state != 'pending':
        problem(409, '此授权请求已经处理，请回到桌面继续')
    item.state = 'approved' if body.approve else 'denied'
    item.member_id, item.company_id, item.session_id = actor.id, actor.company_id, request.state.session.id
    return {'ok': True}


@router.post('/api/v1/desktop/login/exchange')
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


@router.get('/api/v1/desktop/me')
async def me(request: Request, actor=DESKTOP, db=DB):
    return identity_dto(actor, await db.get(Company, actor.company_id), request.state.desktop_session.expires_at)


@router.post('/api/v1/desktop/logout')
async def logout(request: Request, actor=DESKTOP, db=DB):
    await db.delete(request.state.desktop_session)
    return {'ok': True}
