import logging
import secrets
from datetime import timedelta
from fastapi import Depends, Request
from app.core.errors import problem
from app.core.input_rules import PASSWORD_RULES
from app.core.schemas import Input
from app.db.base import now
from app.modules.auth.models import DingTalkAuthorization, DingTalkConfig
from app.modules.auth.sessions import digest, limit_authenticated_request, throttle
from app.modules.members.models import Company
from app.security.secrets import decrypt
from pydantic import Field
from sqlalchemy import delete, select, update
from urllib.parse import urlencode, urlsplit


async def rate(request, key):
    async with request.app.state.sessions.begin() as db:
        await throttle(db, 'dingtalk:' + key + ':' + (request.client.host if request.client else 'unknown'))


async def account_rate(request: Request):
    await limit_authenticated_request(request.app.state.sessions, request, 'dingtalk-account')


async def start(db, request, response, config, purpose, actor=None):
    if not available(config, purpose):
        problem(409, '钉钉登录未启用或配置不完整', 'dingtalk_unavailable')
    # Detect unreadable credentials before sending the browser off-site.
    decrypt(request.app.state.settings.model_key_file, config.credential, config.company_id, 'dingtalk', config.revision)
    state, browser = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    expired = select(DingTalkAuthorization.id).where(DingTalkAuthorization.expires_at < now() - timedelta(minutes=5)).order_by(DingTalkAuthorization.expires_at).limit(100)
    await db.execute(delete(DingTalkAuthorization).where(DingTalkAuthorization.id.in_(expired)))
    db.add(DingTalkAuthorization(company_id=config.company_id, state_hash=digest(state), browser_hash=digest(browser), config_revision=config.revision, purpose=purpose, member_id=actor.id if actor else None, session_id=request.state.session.id if actor else None, expires_at=now() + timedelta(minutes=5)))
    response.set_cookie(BROWSER_COOKIE, browser, httponly=True, secure=request.app.state.settings.cookie_secure, samesite='lax', max_age=300, path='/api/v1/auth/dingtalk')
    response.delete_cookie(PROOF_COOKIE, path='/api/v1/auth')
    return {'url': 'https://login.dingtalk.com/oauth2/auth?' + urlencode({'client_id': config.client_id, 'redirect_uri': callback_url(request.app.state.settings), 'response_type': 'code', 'scope': 'openid corpid', 'state': state, 'prompt': 'consent'})}


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

ACCOUNT_RATE = Depends(account_rate)
