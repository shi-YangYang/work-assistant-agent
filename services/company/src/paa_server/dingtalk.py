"""Company-scoped browser OAuth. Only login grants may provision employees."""
import asyncio
import json
import logging
from datetime import timedelta
import secrets
from urllib.parse import urlencode, urlsplit

from fastapi import Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import Field
from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError

from . import business_access as business
from . import report_schedule as reporting
from .authentication import COOKIE, digest, issue_session, limit_authenticated_request, revoke_member, throttle, verify_password
from .dingtalk_provider import DingTalkError, DingTalkProvider
from .model_secrets import SecretUnavailable, decrypt, encrypt
from .models import Company, DingTalkAuthorization, DingTalkConfig, DingTalkIdentity, Member, Session, now
from .schemas import Input
from .input_rules import PASSWORD_RULES
from .service import problem

BROWSER_COOKIE = 'paa_dingtalk_browser'
PROOF_COOKIE = 'paa_dingtalk_proof'
CALLBACK = '/api/v1/auth/dingtalk/callback'
auth_log = logging.getLogger('uvicorn.error.paa_dingtalk')


class Configuration(Input):
    corpId: str = Field(min_length=1, max_length=128, pattern=r'^\S+$')
    clientId: str = Field(min_length=1, max_length=128, pattern=r'^\S+$')
    secret: str = Field(default='', max_length=512)
    enabled: bool
    expectedRevision: int = Field(ge=0)


class AccountVerification(Input):
    currentPassword: str = Field(default='', max_length=PASSWORD_RULES['max'])
    useDingTalk: bool = False


def callback_url(settings):
    origin = urlsplit(settings.web_origin)
    if origin.scheme not in ('http', 'https') or not origin.netloc or origin.path or origin.query or origin.fragment or origin.username or (settings.cookie_secure and origin.scheme != 'https'):
        problem(503, '登录回调地址未正确配置，请联系部署管理员')
    return settings.web_origin + CALLBACK


async def configuration(db, company_id):
    return await db.scalar(select(DingTalkConfig).where(DingTalkConfig.company_id == company_id).execution_options(populate_existing=True))


def available(config, purpose='login'):
    return bool(config and config.credential and config.corp_id and config.client_id and (config.enabled or purpose == 'probe'))


async def login_company(db, settings):
    if settings.login_company_id:
        return await db.get(Company, settings.login_company_id)
    candidates = (await db.scalars(select(Company).limit(2))).all()
    return candidates[0] if len(candidates) == 1 else None


def config_dto(config, settings):
    return {'corpId': config.corp_id if config else '', 'clientId': config.client_id if config else '', 'hasSecret': bool(config and config.credential), 'enabled': bool(config and config.enabled), 'revision': config.revision if config else 0, 'callbackUrl': callback_url(settings), 'verifiedAt': config.verified_at.isoformat() if config and config.verified_at else None}


async def proof(db, request, actor, consume=False):
    value = request.cookies.get(PROOF_COOKIE, '')
    if not value or len(value) > 128:
        return False
    config = await configuration(db, actor.company_id)
    if not available(config):
        return False
    criteria = (
        DingTalkAuthorization.proof_hash == digest(value),
        DingTalkAuthorization.company_id == actor.company_id,
        DingTalkAuthorization.member_id == actor.id,
        DingTalkAuthorization.session_id == request.state.session.id,
        DingTalkAuthorization.config_revision == config.revision,
        DingTalkAuthorization.purpose == 'reauth',
        DingTalkAuthorization.revoked.is_(False),
        DingTalkAuthorization.proof_used_at.is_(None),
        DingTalkAuthorization.proof_expires_at > now(),
    )
    if consume:
        return bool(await db.scalar(update(DingTalkAuthorization).where(*criteria).values(proof_used_at=now()).returning(DingTalkAuthorization.id)))
    return bool(await db.scalar(select(DingTalkAuthorization.id).where(*criteria)))


def clear_auth_cookies(response):
    response.delete_cookie(BROWSER_COOKIE, path='/api/v1/auth/dingtalk')
    response.delete_cookie(PROOF_COOKIE, path='/api/v1/auth')


def register_routes(app, AUTH, ADMIN, DB, settings, sessions):
    app.state.dingtalk_provider = DingTalkProvider()

    async def rate(request, key):
        async with sessions.begin() as db:
            await throttle(db, 'dingtalk:' + key + ':' + (request.client.host if request.client else 'unknown'))

    async def account_rate(request: Request):
        await limit_authenticated_request(sessions, request, 'dingtalk-account')

    ACCOUNT_RATE = Depends(account_rate)

    async def start(db, request, response, config, purpose, actor=None):
        if not available(config, purpose):
            problem(409, '钉钉登录未启用或配置不完整', 'dingtalk_unavailable')
        # Detect unreadable credentials before sending the browser off-site.
        decrypt(settings.model_key_file, config.credential, config.company_id, 'dingtalk', config.revision)
        state, browser = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        expired = select(DingTalkAuthorization.id).where(DingTalkAuthorization.expires_at < now() - timedelta(minutes=5)).order_by(DingTalkAuthorization.expires_at).limit(100)
        await db.execute(delete(DingTalkAuthorization).where(DingTalkAuthorization.id.in_(expired)))
        db.add(DingTalkAuthorization(company_id=config.company_id, state_hash=digest(state), browser_hash=digest(browser), config_revision=config.revision, purpose=purpose, member_id=actor.id if actor else None, session_id=request.state.session.id if actor else None, expires_at=now() + timedelta(minutes=5)))
        response.set_cookie(BROWSER_COOKIE, browser, httponly=True, secure=settings.cookie_secure, samesite='lax', max_age=300, path='/api/v1/auth/dingtalk')
        response.delete_cookie(PROOF_COOKIE, path='/api/v1/auth')
        return {'url': 'https://login.dingtalk.com/oauth2/auth?' + urlencode({'client_id': config.client_id, 'redirect_uri': callback_url(settings), 'response_type': 'code', 'scope': 'openid corpid', 'state': state, 'prompt': 'consent'})}

    @app.get('/api/v1/auth/providers')
    async def providers(db=DB):
        company = await login_company(db, settings)
        config = await configuration(db, company.id) if company else None
        return {'password': True, 'dingtalk': available(config)}

    @app.get('/api/v1/settings/login/dingtalk')
    async def get_configuration(actor=ADMIN, db=DB):
        return config_dto(await configuration(db, actor.company_id), settings)

    @app.put('/api/v1/settings/login/dingtalk')
    async def save_configuration(body: Configuration, actor=ADMIN, db=DB):
        config = await configuration(db, actor.company_id)
        if body.expectedRevision != (config.revision if config else 0):
            problem(409, '登录配置已更新，请刷新后重试', 'revision_conflict')
        if config and (config.corp_id != body.corpId or config.client_id != body.clientId):
            if await db.scalar(select(DingTalkIdentity.id).where(DingTalkIdentity.company_id == actor.company_id).limit(1)):
                problem(409, '此应用已有账号绑定，请先处理应用迁移，不能直接更换企业或应用', 'identity_migration_required')
            if not body.secret:
                problem(422, '更换企业或应用时请提供新 Secret')
        old_secret = decrypt(settings.model_key_file, config.credential, actor.company_id, 'dingtalk', config.revision) if config and config.credential and not body.secret else ''
        secret = body.secret or old_secret
        if not secret.strip():
            problem(422, '请先配置 Client Secret')
        if config is None:
            config = DingTalkConfig(company_id=actor.company_id, corp_id=body.corpId, client_id=body.clientId, revision=0)
            db.add(config)
        credentials_changed = config.corp_id != body.corpId or config.client_id != body.clientId or bool(body.secret)
        config.revision += 1
        config.corp_id, config.client_id, config.enabled = body.corpId, body.clientId, body.enabled
        config.credential = encrypt(settings.model_key_file, secret, actor.company_id, 'dingtalk', config.revision)
        if credentials_changed:
            config.verified_at = None
        await db.execute(update(DingTalkAuthorization).where(DingTalkAuthorization.company_id == actor.company_id).values(revoked=True, proof_hash=None))
        await db.flush()
        return config_dto(config, settings)

    @app.post('/api/v1/auth/dingtalk/start')
    async def login_start(request: Request, response: Response, db=DB):
        await rate(request, 'login')
        company = await login_company(db, settings)
        config = await configuration(db, company.id) if company else None
        return await start(db, request, response, config, 'login')

    @app.post('/api/v1/settings/login/dingtalk/probe')
    async def probe(request: Request, response: Response, limited=ACCOUNT_RATE, actor=ADMIN, db=DB):
        return await start(db, request, response, await configuration(db, actor.company_id), 'probe', actor)

    @app.get('/api/v1/auth/dingtalk/account')
    async def account(request: Request, actor=AUTH, db=DB):
        bound = await db.scalar(select(DingTalkIdentity.id).where(DingTalkIdentity.member_id == actor.id, DingTalkIdentity.company_id == actor.company_id))
        return {'bound': bool(bound), 'hasPassword': bool(actor.password_hash), 'available': available(await configuration(db, actor.company_id)), 'passwordVerified': await proof(db, request, actor)}

    @app.post('/api/v1/auth/dingtalk/account/bind')
    async def bind(body: AccountVerification, request: Request, response: Response, limited=ACCOUNT_RATE, actor=AUTH, db=DB):
        if not await verify_password(body.currentPassword, actor.password_hash):
            raise HTTPException(400, detail={'code': 'invalid_current_password', 'message': '当前密码不正确', 'fieldErrors': {'currentPassword': '当前密码不正确'}})
        if await db.scalar(select(DingTalkIdentity.id).where(DingTalkIdentity.member_id == actor.id)):
            problem(409, '此账号已绑定钉钉；更换前请先验证并解绑')
        return await start(db, request, response, await configuration(db, actor.company_id), 'bind', actor)

    @app.post('/api/v1/auth/dingtalk/account/reauth')
    async def reauth(request: Request, response: Response, limited=ACCOUNT_RATE, actor=AUTH, db=DB):
        if not await db.scalar(select(DingTalkIdentity.id).where(DingTalkIdentity.member_id == actor.id, DingTalkIdentity.company_id == actor.company_id)):
            problem(409, '请先绑定钉钉账号')
        return await start(db, request, response, await configuration(db, actor.company_id), 'reauth', actor)

    @app.post('/api/v1/auth/dingtalk/account/unbind')
    async def unbind(body: AccountVerification, request: Request, response: Response, limited=ACCOUNT_RATE, actor=AUTH, db=DB):
        if not actor.password_hash:
            problem(409, '请先设置本地密码，再解绑钉钉')
        valid = await proof(db, request, actor, consume=True) if body.useDingTalk else await verify_password(body.currentPassword, actor.password_hash)
        if not valid:
            if body.useDingTalk:
                problem(400, '钉钉验证已过期，请重新验证')
            raise HTTPException(400, detail={'code': 'invalid_current_password', 'message': '当前密码不正确', 'fieldErrors': {'currentPassword': '当前密码不正确'}})
        await db.execute(delete(DingTalkIdentity).where(DingTalkIdentity.company_id == actor.company_id, DingTalkIdentity.member_id == actor.id))
        await revoke_member(db, actor.id)
        response.delete_cookie(COOKIE, path='/')
        clear_auth_cookies(response)
        return {'ok': True}

    def result(request, purpose='login', status='failed', reason='failed'):
        destination = '/settings/login' if purpose == 'probe' else '/settings/account' if purpose in ('bind', 'reauth') else '/assistant'
        query = {'dingtalk': status}
        if status == 'failed':
            query.update(reason=reason, requestId=request.state.request_id)
        response = RedirectResponse(settings.web_origin + destination + '?' + urlencode(query), status_code=303)
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.delete_cookie(BROWSER_COOKIE, path='/api/v1/auth/dingtalk')
        return response

    async def complete_callback(request: Request):
        state = request.query_params.get('state', '')
        browser = request.cookies.get(BROWSER_COOKIE, '')
        code = request.query_params.get('authCode') or request.query_params.get('code', '')
        purpose = 'login'
        if not state or not browser or len(state) > 128 or len(browser) > 128:
            return result(request, reason='expired')
        # Atomically consume before any external request. A replay, cancelled
        # authorization or network failure cannot reuse the grant/code.
        async with sessions.begin() as db:
            grant = await db.scalar(update(DingTalkAuthorization).where(DingTalkAuthorization.state_hash == digest(state), DingTalkAuthorization.browser_hash == digest(browser), DingTalkAuthorization.consumed_at.is_(None), DingTalkAuthorization.revoked.is_(False), DingTalkAuthorization.expires_at > now()).values(consumed_at=now()).returning(DingTalkAuthorization))
            if grant is None:
                return result(request, reason='expired')
            purpose = grant.purpose
            grant_id, company_id, revision = grant.id, grant.company_id, grant.config_revision
            config = await configuration(db, company_id)
            if not available(config, purpose) or config.revision != revision:
                return result(request, purpose, reason='unavailable')
            if request.query_params.get('error') or not code or len(code) > 2048:
                return result(request, purpose, reason='cancelled')
            try:
                secret = decrypt(settings.model_key_file, config.credential, company_id, 'dingtalk', revision)
            except SecretUnavailable:
                return result(request, purpose, reason='unavailable')
            corp_id, client_id = config.corp_id, config.client_id
        try:
            # No company/session lock is held while waiting on the provider.
            async with asyncio.timeout(45):
                verified = await app.state.dingtalk_provider.verify(corp_id, client_id, secret, code)
            async with sessions.begin() as db:
                await business.company_lock(db, company_id)
                config = await configuration(db, company_id)
                grant = await db.get(DingTalkAuthorization, grant_id)
                if not available(config, purpose) or config.revision != revision or grant is None or grant.revoked or grant.expires_at <= now():
                    return result(request, purpose, reason='expired')
                actor = None
                if purpose != 'login':
                    actor = await db.get(Member, grant.member_id)
                    session = await db.get(Session, grant.session_id)
                    if not actor or not actor.active or actor.company_id != company_id or not session or session.expires_at <= now() or session.member_id != actor.id or session.token_hash != digest(request.cookies.get(COOKIE, '')):
                        return result(request, purpose, reason='expired')
                    if purpose == 'probe' and actor.role != 'admin':
                        return result(request, purpose, reason='denied')
                link = await db.scalar(select(DingTalkIdentity).where(DingTalkIdentity.company_id == company_id, DingTalkIdentity.corp_id == corp_id, DingTalkIdentity.client_id == client_id, or_(DingTalkIdentity.union_id == verified.union_id, DingTalkIdentity.user_id == verified.user_id)))
                if link and (link.union_id != verified.union_id or link.user_id != verified.user_id):
                    return result(request, purpose, reason='conflict')
                if purpose == 'probe':
                    config.verified_at = now()
                    return result(request, purpose, 'verified')
                if purpose == 'reauth':
                    if not link or link.member_id != actor.id:
                        return result(request, purpose, reason='denied')
                    token = secrets.token_urlsafe(32)
                    grant.proof_hash, grant.proof_expires_at = digest(token), now() + timedelta(minutes=5)
                    response = result(request, purpose, 'verified')
                    response.set_cookie(PROOF_COOKIE, token, httponly=True, secure=settings.cookie_secure, samesite='lax', max_age=300, path='/api/v1/auth')
                    return response
                if purpose == 'bind':
                    existing = await db.scalar(select(DingTalkIdentity.id).where(DingTalkIdentity.member_id == actor.id))
                    if link or existing:
                        return result(request, purpose, reason='conflict')
                elif link:
                    actor = await db.get(Member, link.member_id)
                    if not actor or not actor.active or actor.company_id != company_id:
                        return result(request, purpose, reason='denied')
                else:
                    # Username collisions (including another company) use an
                    # isolated savepoint, preserving the whole login transaction.
                    for _ in range(5):
                        try:
                            async with db.begin_nested():
                                actor = Member(company_id=company_id, username='dd_' + secrets.token_hex(10), name=verified.name, role='employee', password_hash=None)
                                db.add(actor)
                                await db.flush()
                            break
                        except IntegrityError:
                            actor = None
                    if actor is None:
                        raise DingTalkError('conflict')
                    await reporting.eligibility_changed(db, actor)
                if not link:
                    db.add(DingTalkIdentity(company_id=company_id, member_id=actor.id, corp_id=corp_id, client_id=client_id, union_id=verified.union_id, user_id=verified.user_id))
                    await db.flush()
                response = result(request, purpose, 'bound' if purpose == 'bind' else 'logged-in')
                if purpose == 'bind':
                    # Binding changes a login identity. Replace all older sessions
                    # with a new session for this successfully verified browser.
                    await revoke_member(db, actor.id)
                else:
                    previous = request.cookies.get(COOKIE, '')
                    if previous:
                        await db.execute(delete(Session).where(Session.token_hash == digest(previous)))
                issue_session(db, actor, response, settings)
                return response
        except (DingTalkError, TimeoutError) as error:
            reason = getattr(error, 'reason', 'unavailable')
            diagnostics = error.diagnostics if isinstance(error, DingTalkError) else {'stage': 'provider_timeout', 'httpStatus': None, 'vendorCode': None, 'vendorSubCode': None}
            auth_log.info('dingtalk %s', json.dumps({'requestId': request.state.request_id, 'reason': reason, **diagnostics}, ensure_ascii=True))
            return result(request, purpose, reason=reason)
        except IntegrityError:
            return result(request, purpose, reason='conflict')

    @app.get(CALLBACK)
    async def callback(request: Request):
        try:
            return await complete_callback(request)
        except Exception as error:
            # Never put provider payloads or callback query strings in logs.
            request.state.exception_type = type(error).__name__
            return result(request, reason='failed')
