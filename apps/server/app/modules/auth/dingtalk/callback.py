import asyncio
import json
import secrets
from datetime import timedelta
from fastapi import Request
from fastapi.responses import RedirectResponse
from app.db.base import now
from app.integrations.dingtalk import DingTalkError
from app.modules.auth.dingtalk.service import BROWSER_COOKIE, PROOF_COOKIE, auth_log, available, configuration
from app.modules.auth.models import DingTalkAuthorization, DingTalkIdentity, Session
from app.modules.auth.sessions import COOKIE, digest, issue_session, revoke_member
from app.modules.members.models import Member
from app.modules.reports.schedule import eligibility_changed as reporting_eligibility_changed
from app.security.locks import company_lock as business_company_lock
from app.security.secrets import SecretUnavailable, decrypt
from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from urllib.parse import urlencode


def result(request, purpose='login', status='failed', reason='failed'):
    destination = '/settings/login' if purpose == 'probe' else '/settings/account' if purpose in ('bind', 'reauth') else '/assistant'
    query = {'dingtalk': status}
    if status == 'failed':
        query.update(reason=reason, requestId=request.state.request_id)
    response = RedirectResponse(request.app.state.settings.web_origin + destination + '?' + urlencode(query), status_code=303)
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
    async with request.app.state.sessions.begin() as db:
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
            secret = decrypt(request.app.state.settings.model_key_file, config.credential, company_id, 'dingtalk', revision)
        except SecretUnavailable:
            return result(request, purpose, reason='unavailable')
        corp_id, client_id = config.corp_id, config.client_id
    try:
        # No company/session lock is held while waiting on the provider.
        async with asyncio.timeout(45):
            verified = await request.app.state.dingtalk_provider.verify(corp_id, client_id, secret, code)
        async with request.app.state.sessions.begin() as db:
            await business_company_lock(db, company_id)
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
                response.set_cookie(PROOF_COOKIE, token, httponly=True, secure=request.app.state.settings.cookie_secure, samesite='lax', max_age=300, path='/api/v1/auth')
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
                await reporting_eligibility_changed(db, actor)
            if not link:
                db.add(DingTalkIdentity(company_id=company_id, member_id=actor.id, corp_id=corp_id, client_id=client_id, union_id=verified.union_id, user_id=verified.user_id))
                await db.flush()
            response = result(request, purpose, 'bound' if purpose == 'bind' else 'logged-in')
            if purpose == 'bind':
                # Binding changes a login identity. Replace all older request.app.state.sessions
                # with a new session for this successfully verified browser.
                await revoke_member(db, actor.id)
            else:
                previous = request.cookies.get(COOKIE, '')
                if previous:
                    await db.execute(delete(Session).where(Session.token_hash == digest(previous)))
            issue_session(db, actor, response, request.app.state.settings)
            return response
    except (DingTalkError, TimeoutError) as error:
        reason = getattr(error, 'reason', 'unavailable')
        diagnostics = error.diagnostics if isinstance(error, DingTalkError) else {'stage': 'provider_timeout', 'httpStatus': None, 'vendorCode': None, 'vendorSubCode': None}
        auth_log.info('dingtalk %s', json.dumps({'requestId': request.state.request_id, 'reason': reason, **diagnostics}, ensure_ascii=True))
        return result(request, purpose, reason=reason)
    except IntegrityError:
        return result(request, purpose, reason='conflict')
