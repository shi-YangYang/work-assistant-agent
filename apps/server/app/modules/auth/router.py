import hashlib
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from app.core.errors import problem
from app.db.base import now
from app.http.dependencies import AUTH, DB, SESSIONS, SETTINGS
from app.modules.auth.models import DingTalkAuthorization, LoginAttempt
from app.modules.auth.schemas import Login, Password
from app.modules.auth.sessions import COOKIE, issue_session, limit_authenticated_request, passwords, revoke_member, verify_password
from app.modules.members.models import Company, Member
from app.modules.members.serializers import member_dto
from app.security.locks import company_lock as business_company_lock
from sqlalchemy import delete, func, select, update
from starlette.concurrency import run_in_threadpool

router = APIRouter()


@router.post('/api/v1/auth/login')
async def login(body: Login, response: Response, request: Request, db=DB, settings=SETTINGS):
    ident = hashlib.sha256(f'{request.client.host}:{body.username.lower()}'.encode()).hexdigest()
    recent = now() - timedelta(minutes=10)
    count = await db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.identity == ident, LoginAttempt.created_at > recent))
    if count >= 8:
        problem(429, '尝试次数过多，请 10 分钟后重试')
    actor = await db.scalar(select(Member).where(Member.username == body.username.lower()))
    checked_hash = actor.password_hash if actor else None
    valid = await verify_password(body.password, checked_hash)
    if valid and actor is not None:
        # Password checks are expensive: verify outside the company lock,
        # then serialize issuance with password resets and member disable.
        await business_company_lock(db, actor.company_id)
        actor = await db.scalar(select(Member).where(Member.id == actor.id).execution_options(populate_existing=True))
        valid = bool(actor and actor.password_hash == checked_hash)
    if not valid or actor is None or not actor.active:
        db.add(LoginAttempt(identity=ident))
        await db.commit()
        problem(401, '账号或密码不正确')
    await db.execute(delete(LoginAttempt).where(LoginAttempt.identity == ident))
    csrf = issue_session(db, actor, response, settings)
    company = await db.get(Company, actor.company_id)
    return {'member': member_dto(actor), 'csrf': csrf, 'company': {'id': company.id, 'name': company.name}}


@router.get('/api/v1/auth/me')
async def me(request: Request, actor=AUTH, db=DB):
    company = await db.get(Company, actor.company_id)
    return {'member': member_dto(actor), 'csrf': request.state.session.csrf, 'company': {'id': company.id, 'name': company.name}}


@router.post('/api/v1/auth/logout')
async def logout(response: Response, request: Request, actor=AUTH, db=DB):
    await db.execute(update(DingTalkAuthorization).where(DingTalkAuthorization.session_id == request.state.session.id).values(revoked=True, proof_hash=None))
    await db.delete(request.state.session)
    response.delete_cookie(COOKIE, path='/')
    return {'ok': True}


async def password_rate(request: Request, sessions=SESSIONS):
    await limit_authenticated_request(sessions, request, 'password')


@router.post('/api/v1/auth/password')
async def password(body: Password, response: Response, request: Request, limited=Depends(password_rate), actor=AUTH, db=DB):
    from app.modules.auth.dingtalk.service import proof, clear_auth_cookies
    valid = await proof(db, request, actor, consume=True) if body.useDingTalk else await verify_password(body.currentPassword, actor.password_hash)
    if not valid:
        if body.useDingTalk:
            problem(400, '钉钉验证已过期，请重新验证')
        raise HTTPException(400, detail={'code': 'invalid_current_password', 'message': '当前密码不正确', 'fieldErrors': {'currentPassword': '当前密码不正确'}})
    clear_auth_cookies(response)
    actor.password_hash = await run_in_threadpool(passwords.hash, body.newPassword)
    await revoke_member(db, actor.id)
    response.delete_cookie(COOKIE, path='/')
    return {'ok': True}
