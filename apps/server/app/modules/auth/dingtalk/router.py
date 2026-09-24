from fastapi import APIRouter, HTTPException, Request, Response
from app.core.errors import problem
from app.http.dependencies import ADMIN, AUTH, DB, SETTINGS
from app.modules.auth.dingtalk.callback import complete_callback, result
from app.modules.auth.dingtalk.service import ACCOUNT_RATE, AccountVerification, CALLBACK, Configuration, available, clear_auth_cookies, config_dto, configuration, login_company, proof, rate, start
from app.modules.auth.models import DingTalkAuthorization, DingTalkConfig, DingTalkIdentity
from app.modules.auth.sessions import COOKIE, revoke_member, verify_password
from app.security.secrets import decrypt, encrypt
from sqlalchemy import delete, select, update

router = APIRouter()


@router.get('/api/v1/auth/providers')
async def providers(db=DB, settings=SETTINGS):
    company = await login_company(db, settings)
    config = await configuration(db, company.id) if company else None
    return {'password': True, 'dingtalk': available(config)}


@router.get('/api/v1/settings/login/dingtalk')
async def get_configuration(actor=ADMIN, db=DB, settings=SETTINGS):
    return config_dto(await configuration(db, actor.company_id), settings)


@router.put('/api/v1/settings/login/dingtalk')
async def save_configuration(body: Configuration, actor=ADMIN, db=DB, settings=SETTINGS):
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


@router.post('/api/v1/auth/dingtalk/start')
async def login_start(request: Request, response: Response, db=DB):
    await rate(request, 'login')
    company = await login_company(db, request.app.state.settings)
    config = await configuration(db, company.id) if company else None
    return await start(db, request, response, config, 'login')


@router.post('/api/v1/settings/login/dingtalk/probe')
async def probe(request: Request, response: Response, limited=ACCOUNT_RATE, actor=ADMIN, db=DB):
    return await start(db, request, response, await configuration(db, actor.company_id), 'probe', actor)


@router.get('/api/v1/auth/dingtalk/account')
async def account(request: Request, actor=AUTH, db=DB):
    bound = await db.scalar(select(DingTalkIdentity.id).where(DingTalkIdentity.member_id == actor.id, DingTalkIdentity.company_id == actor.company_id))
    return {'bound': bool(bound), 'hasPassword': bool(actor.password_hash), 'available': available(await configuration(db, actor.company_id)), 'passwordVerified': await proof(db, request, actor)}


@router.post('/api/v1/auth/dingtalk/account/bind')
async def bind(body: AccountVerification, request: Request, response: Response, limited=ACCOUNT_RATE, actor=AUTH, db=DB):
    if not await verify_password(body.currentPassword, actor.password_hash):
        raise HTTPException(400, detail={'code': 'invalid_current_password', 'message': '当前密码不正确', 'fieldErrors': {'currentPassword': '当前密码不正确'}})
    if await db.scalar(select(DingTalkIdentity.id).where(DingTalkIdentity.member_id == actor.id)):
        problem(409, '此账号已绑定钉钉；更换前请先验证并解绑')
    return await start(db, request, response, await configuration(db, actor.company_id), 'bind', actor)


@router.post('/api/v1/auth/dingtalk/account/reauth')
async def reauth(request: Request, response: Response, limited=ACCOUNT_RATE, actor=AUTH, db=DB):
    if not await db.scalar(select(DingTalkIdentity.id).where(DingTalkIdentity.member_id == actor.id, DingTalkIdentity.company_id == actor.company_id)):
        problem(409, '请先绑定钉钉账号')
    return await start(db, request, response, await configuration(db, actor.company_id), 'reauth', actor)


@router.post('/api/v1/auth/dingtalk/account/unbind')
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


@router.get(CALLBACK)
async def callback(request: Request):
    try:
        return await complete_callback(request)
    except Exception as error:
        # Never put provider payloads or callback query strings in logs.
        request.state.exception_type = type(error).__name__
        return result(request, reason='failed')
