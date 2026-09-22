import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
import hashlib
import json
import logging
import secrets
from pathlib import Path
from time import perf_counter
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.requests import ClientDisconnect

from .desktop_auth import NATIVE_WRITES
from .authentication import COOKIE, passwords, issue_session, limit_authenticated_request, revoke_member, verify_password
from . import business_access as business
from . import report_schedule as reporting
from .report_queries import report_dto, report_dtos
from . import business_actions as actions
from . import business_writes as writes
from .documents import attachment_dto, chunk_page, document_type, safe_name, visible_attachment
from .config import Settings
from .db import database
from .media import audio_mime, audio_wav, image_process, preview_path
from .models import BusinessAction, Conversation, Attachment, Company, Job, LoginAttempt, Member, Message, ProgressDraft, Report, ReportRevision, ReportObligation, ReportNotification, Session, DingTalkAuthorization, WorkItem, WorkRevision, now
from .model_schemas import RetryJob
from .model_provider import ProviderError
from .model_secrets import SecretUnavailable
from .schemas import ConversationCreate, ConversationEdit, Confirm, DraftEdit, GenerateReport, Login, MemberCreate, MemberPatch, Password, ReportEdit, ResetPassword, Revision, Rules, SendMessage, TranscriptEdit, WorkEdit, Progress
from .schemas import member_validation_errors
from .service import active_message, conversation_dto, default_conversation, confirm_drafts, draft_dto, ensure_report, idem_begin, idem_save, job_dto, member_dto, owned, problem, version, work_dto

request_log = logging.getLogger('uvicorn.error.paa_requests')


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        size = 0
        async def bounded():
            nonlocal size
            message = await receive()
            size += len(message.get('body', b''))
            if size > 25 * 1024 * 1024:
                problem(413, '上传总大小不能超过 25 MiB')
            return message
        await self.app(scope, bounded, send)


def create_app(settings=None):
    settings = settings or Settings()
    engine, sessions = database(settings)

    @asynccontextmanager
    async def lifespan(app):
        settings.media_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        yield
        await engine.dispose()

    app = FastAPI(title='Company Work Assistant', version='0.1.0', lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.sessions = sessions
    app.state.settings = settings
    app.add_middleware(BodyLimit)
    # Uvicorn's default access line contains the full URL/query. The correlated
    # request summary below deliberately records only a registered route template.
    logging.getLogger('uvicorn.access').disabled = True

    class Boundaries:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope['type'] != 'http':
                return await self.app(scope, receive, send)
            request = Request(scope, receive)
            request.state.request_id = str(uuid4())
            request.state.exception_type = None
            started, status = perf_counter(), None

            async def correlated_send(message):
                nonlocal status
                if message['type'] == 'http.response.start':
                    status = message['status']
                    headers = MutableHeaders(scope=message)
                    headers.setdefault('Cache-Control', 'no-store')
                    headers.setdefault('Referrer-Policy', 'same-origin')
                    headers.update({'X-Content-Type-Options': 'nosniff', 'X-Request-ID': request.state.request_id})
                await send(message)

            try:
                native = request.url.path in NATIVE_WRITES and request.headers.get('origin') is None
                if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('origin') != settings.web_origin and not native:
                    response = JSONResponse({'error': {'code': 'origin_rejected', 'message': '请求来源不被允许', 'requestId': request.state.request_id}}, status_code=403)
                    await response(scope, receive, correlated_send)
                else:
                    await self.app(scope, receive, correlated_send)
            except asyncio.CancelledError:
                request.state.exception_type = 'CancelledError'
                raise
            except ClientDisconnect:
                request.state.exception_type = 'ClientDisconnect'
            except Exception as error:
                request.state.exception_type = type(error).__name__
                if status is not None:
                    # Headers are already on the wire. Leave a failed stream
                    # incomplete so the server closes it, without forwarding
                    # private exceptions to its traceback logger or pretending
                    # that the response body completed successfully.
                    return
                if isinstance(error, HTTPException):
                    response = await http_error(request, error)
                elif isinstance(error, SQLAlchemyError):
                    response = JSONResponse({'error': {'code': 'service_unavailable', 'message': '服务暂不可用，请稍后重试', 'requestId': request.state.request_id}}, status_code=503)
                else:
                    response = JSONResponse({'error': {'code': 'internal_error', 'message': '服务处理失败，请稍后重试', 'requestId': request.state.request_id}}, status_code=500)
                await response(scope, receive, correlated_send)
            finally:
                request_log.info('request %s', json.dumps({
                    'requestId': request.state.request_id,
                    'route': getattr(scope.get('route'), 'path', '<unmatched>'),
                    'status': status,
                    'durationMs': round((perf_counter() - started) * 1000, 2),
                    'exceptionType': request.state.exception_type,
                }, ensure_ascii=True))

    app.add_middleware(Boundaries)

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        request.state.exception_type = type(error).__name__
        detail = error.detail if isinstance(error.detail, dict) else {'code': 'invalid_request', 'message': str(error.detail)}
        return JSONResponse({'error': {**detail, 'requestId': request.state.request_id}}, status_code=error.status_code, headers=error.headers)

    @app.exception_handler(ProviderError)
    @app.exception_handler(SecretUnavailable)
    async def model_error(request, error):
        request.state.exception_type = type(error).__name__
        return JSONResponse({'error': {'code': getattr(error, 'code', 'secret_unavailable'), 'message': str(error), 'requestId': request.state.request_id}}, status_code=422 if isinstance(error, ProviderError) else 503)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        request.state.exception_type = type(error).__name__
        errors = error.errors()
        detail = {'code': 'validation_error', 'message': '请检查输入内容、日期和长度限制', 'requestId': request.state.request_id, 'fields': ['.'.join(map(str, e['loc'])) for e in errors]}
        reset = request.url.path.startswith('/api/v1/members/') and request.url.path.endswith('/reset-password')
        if request.url.path == '/api/v1/members' or reset:
            fields = member_validation_errors(errors, reset=reset)
            if fields:
                detail.update(message='请检查标记的输入项', fieldErrors=fields)
        return JSONResponse({'error': detail}, status_code=422)

    async def db_dep():
        async with sessions() as db:
            try:
                yield db
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    # Complete writes before sending success, so an immediate read sees them
    # and a failed commit cannot be reported to the client as a successful save.
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
                await business.company_lock(db, actor.company_id)
                session = await db.scalar(select(Session).where(Session.id == session.id, Session.expires_at > now()).execution_options(populate_existing=True))
            actor = await db.scalar(select(Member).where(Member.id == actor.id).execution_options(populate_existing=True))
        if actor is None or not actor.active or session is None:
            problem(401, '登录已过期，请重新登录', 'login_required')
        if request.method not in ('GET', 'HEAD') and not secrets.compare_digest(request.headers.get('x-csrf-token', ''), session.csrf):
            problem(403, '请求校验失败，请刷新后重试', 'csrf_rejected')
        if actor.must_change_password and request.url.path not in ('/api/v1/auth/me', '/api/v1/auth/password', '/api/v1/auth/logout', '/api/v1/auth/dingtalk/account', '/api/v1/auth/dingtalk/account/reauth'):
            problem(403, '请先修改临时密码', 'password_change_required')
        request.state.session = session
        return actor

    AUTH = Depends(identity)

    async def admin(actor=AUTH):
        if actor.role != 'admin':
            problem(403, '仅老板／管理员可进行此操作')
        return actor

    ADMIN = Depends(admin)
    from .model_services import register_routes
    register_routes(app, ADMIN, DB, settings, sessions)
    from .support_feedback import register_routes as register_support_routes
    register_support_routes(app, AUTH, ADMIN, DB)

    from .dingtalk import register_routes as register_dingtalk_routes
    register_dingtalk_routes(app, AUTH, ADMIN, DB, settings, sessions)

    from .desktop_auth import register_routes as register_desktop_routes
    desktop_auth = register_desktop_routes(app, AUTH, DB, settings, sessions)
    from .voiceprints import register_routes as register_voiceprint_routes
    register_voiceprint_routes(app, ADMIN, desktop_auth, DB, settings)
    from .team_workspace import register_routes as register_team_workspace
    register_team_workspace(app, ADMIN, DB)

    async def visible_member(db, actor, member_id, *, employee_only=False):
        target = await db.scalar(select(Member).where(Member.id == member_id, Member.company_id == actor.company_id))
        if target is None or (employee_only and target.role != 'employee') or (actor.role != 'admin' and actor.id != target.id):
            problem(404, '成员不存在或无权查看')
        return target

    async def message_dto(db, item, actor):
        allowed = await business.valid(db, actor, item.access)
        attachments = (await db.scalars(select(Attachment).where(Attachment.message_id == item.id, Attachment.deleted.is_(False)))).all()
        job = await db.scalar(select(Job).where(Job.target_id == item.id, Job.kind == 'message').order_by(Job.created_at.desc()).limit(1))
        private = (await db.scalars(select(ProgressDraft).where(ProgressDraft.message_id == item.id, ProgressDraft.status != 'deleted').order_by(ProgressDraft.created_at))).all() if actor.id == item.owner_id else []
        statuses = {d.id: d.status for d in (await db.scalars(select(ProgressDraft).where(ProgressDraft.message_id == item.id))).all()}
        return {'id': item.id, 'ownerId': item.owner_id, 'conversationId': item.conversation_id, 'text': item.text if allowed else '', 'reply': item.reply if allowed else '', 'businessUnavailable': not allowed, 'citations': [c for c in item.citations if c.get('kind') != 'business'] if allowed else [], 'businessCitations': [c for c in item.citations if c.get('kind') == 'business'] if allowed else [], 'replyTo': item.reply_to, 'transcript': item.transcript if allowed else '', 'transcriptRevision': item.transcript_revision, 'createdAt': item.created_at.isoformat(), 'attachments': [attachment_dto(a) for a in attachments] if allowed else [], 'job': job_dto(job) if job else None, 'drafts': [{**draft_dto(d), 'businessLinks': await business_link_dtos(db, actor, d.business_links)} for d in private if allowed and await business.valid(db, actor, d.access)], 'suggestions': [{**s, 'status': statuses.get(s['id'], 'pending')} for s in item.suggestions] if allowed else [], 'actions': await actions.message_actions(db, actor, item)}

    @app.get('/api/v1/health')
    async def health(db=DB):
        await db.scalar(select(Company.id).limit(1))
        return {'status': 'ready'}

    @app.post('/api/v1/auth/login')
    async def login(body: Login, response: Response, request: Request, db=DB):
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
            await business.company_lock(db, actor.company_id)
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

    @app.get('/api/v1/auth/me')
    async def me(request: Request, actor=AUTH, db=DB):
        company = await db.get(Company, actor.company_id)
        return {'member': member_dto(actor), 'csrf': request.state.session.csrf, 'company': {'id': company.id, 'name': company.name}}

    @app.post('/api/v1/auth/logout')
    async def logout(response: Response, request: Request, actor=AUTH, db=DB):
        await db.execute(update(DingTalkAuthorization).where(DingTalkAuthorization.session_id == request.state.session.id).values(revoked=True, proof_hash=None))
        await db.delete(request.state.session)
        response.delete_cookie(COOKIE, path='/')
        return {'ok': True}

    async def password_rate(request: Request):
        await limit_authenticated_request(sessions, request, 'password')

    @app.post('/api/v1/auth/password')
    async def password(body: Password, response: Response, request: Request, limited=Depends(password_rate), actor=AUTH, db=DB):
        from .dingtalk import proof, clear_auth_cookies
        valid = await proof(db, request, actor, consume=True) if body.useDingTalk else await verify_password(body.currentPassword, actor.password_hash)
        if not valid:
            problem(400, '当前密码不正确或钉钉验证已过期，请重新验证')
        clear_auth_cookies(response)
        actor.password_hash = await run_in_threadpool(passwords.hash, body.newPassword)
        actor.must_change_password = False
        await revoke_member(db, actor.id)
        response.delete_cookie(COOKIE, path='/')
        return {'ok': True}

    @app.get('/api/v1/members')
    async def members(actor=ADMIN, db=DB):
        return {'items': [member_dto(m) for m in (await db.scalars(select(Member).where(Member.company_id == actor.company_id, Member.role == 'employee', Member.deleted.is_(False)).order_by(Member.created_at))).all()]}

    @app.post('/api/v1/members', status_code=201)
    async def add_member(body: MemberCreate, actor=ADMIN, db=DB):
        if body.role != 'employee':
            problem(403, '成员管理仅可添加员工')
        if await db.scalar(select(Member.id).where(Member.username == body.username.lower())):
            raise HTTPException(409, detail={'code': 'username_taken', 'message': '账号名称已被使用', 'fieldErrors': {'username': '账号名称已被使用'}})
        item = Member(company_id=actor.company_id, username=body.username.lower(), name=body.name, role=body.role, password_hash=await run_in_threadpool(passwords.hash, body.password))
        db.add(item)
        await db.flush()
        await reporting.eligibility_changed(db, item)
        return member_dto(item)

    @app.patch('/api/v1/members/{identifier}')
    async def change_member(identifier: str, body: MemberPatch, actor=ADMIN, db=DB):
        await db.scalar(select(Company).where(Company.id == actor.company_id).with_for_update())
        item = await visible_member(db, actor, identifier, employee_only=True)
        if item.deleted:
            problem(404, '账号已删除')
        item.active = body.active
        await reporting.eligibility_changed(db, item)
        if not item.active:
            await revoke_member(db, item.id)
        return member_dto(item)

    @app.post('/api/v1/members/{identifier}/reset-password')
    async def reset_password(identifier: str, body: ResetPassword, actor=ADMIN, db=DB):
        item = await visible_member(db, actor, identifier, employee_only=True)
        if item.deleted:
            problem(404, '账号已删除')
        item.password_hash = await run_in_threadpool(passwords.hash, body.password)
        item.must_change_password = True
        await revoke_member(db, item.id)
        return {'ok': True}

    @app.delete('/api/v1/members/{identifier}')
    async def delete_member(identifier: str, actor=ADMIN, db=DB):
        await db.scalar(select(Company).where(Company.id == actor.company_id).with_for_update())
        item = await visible_member(db, actor, identifier)
        if item.role != 'employee':
            problem(404, '成员不存在或无权查看')
        # Preserve the owner ID for history, but release both login identities.
        # The colon is outside the allowed username alphabet, so this reserved
        # tombstone cannot conflict with an account created through the API.
        if not item.deleted:
            item.active, item.deleted, item.password_hash = False, True, None
            item.username = 'deleted:' + item.id
            await reporting.eligibility_changed(db, item)
            await revoke_member(db, item.id)
            from .models import DingTalkIdentity, Voiceprint
            await db.execute(delete(DingTalkIdentity).where(DingTalkIdentity.member_id == item.id, DingTalkIdentity.company_id == actor.company_id))
            await db.execute(update(Voiceprint).where(Voiceprint.member_id == item.id, Voiceprint.state.in_(('queued', 'processing'))).values(state='failed', error='账号已删除，登记已停止', lease_until=None, revision=Voiceprint.revision + 1, updated_at=now()))
        return {'ok': True}

    @app.post('/api/v1/uploads', status_code=201)
    async def upload(file: UploadFile, actor=AUTH, db=DB):
        name = safe_name(file.filename)
        mime = document_type(name, file.content_type)
        suffix = Path(name).suffix.lower()
        kind = 'document' if mime else 'image' if (file.content_type or '').startswith('image/') or suffix in ('.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif') else 'audio'
        if kind != 'image' and not mime and not ((file.content_type or '').startswith(('audio/', 'image/')) or Path(name).suffix.lower() in ('.m4a', '.wav', '.webm', '.mp4', '.aac', '.mp3')):
            problem(415, '请使用 PDF、DOCX、PPTX、XLSX、TXT、JSON、MD、CSV、图片或语音文件')
        identifier = str(uuid4())
        settings.media_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = settings.media_dir / identifier
        size, digest = 0, hashlib.sha256()
        try:
            with path.open('xb') as target:
                path.chmod(0o600)
                while block := await file.read(65536):
                    size += len(block)
                    if size > (5 if kind == 'image' else 20) * 1024 * 1024:
                        problem(413, '每张图片不能超过 5 MiB' if kind == 'image' else '文件不能超过 20 MiB')
                    digest.update(block)
                    await run_in_threadpool(target.write, block)
            if not size:
                problem(422, '不能上传空文件')
            duration, image_info = None, {}
            if kind == 'image':
                image_info = await image_process(path)
                mime = image_info['mime']
                expected = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp', '.heic': 'image/heic', '.heif': 'image/heic'}.get(suffix)
                if expected and expected != mime:
                    problem(415, '图片实际格式与扩展名不一致，请重新导出后上传')
            elif kind == 'audio':
                with path.open('rb') as raw:
                    mime = audio_mime(raw.read(16))
                _, duration = await audio_wav(path, settings)
            elif Path(name).suffix.lower() in ('.pdf', '.docx', '.pptx', '.xlsx'):
                with path.open('rb') as raw:
                    magic = raw.read(8)
                if not (magic.startswith(b'%PDF-') if name.lower().endswith('.pdf') else magic.startswith(b'PK\x03\x04')):
                    problem(415, '文件结构与扩展名不符或文件已损坏，请重新导出')
            initial_company = actor.company_id
            await business.company_lock(db, initial_company)
            actor = await db.scalar(select(Member).where(Member.id == actor.id).execution_options(populate_existing=True))
            if not actor.active or actor.company_id != initial_company:
                problem(403, '账号权限已变化，请重新登录')
            item = Attachment(id=identifier, company_id=actor.company_id, owner_id=actor.id, kind=kind, mime=mime, name=name, size=size, sha256=digest.hexdigest(), duration=duration, extraction_info=image_info, extraction_status='unsent' if kind == 'document' else 'none')
            db.add(item)
            await db.flush()
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return attachment_dto(item)

    @app.get('/api/v1/uploads/{identifier}/content')
    async def content(identifier: str, actor=AUTH, db=DB):
        item = await visible_attachment(db, identifier, actor)
        path = settings.media_dir / item.id
        if not path.is_file():
            problem(404, '附件文件暂不可用')
        return FileResponse(path, media_type=item.mime, filename=item.name if item.kind == 'document' else None, content_disposition_type='attachment' if item.kind == 'document' else 'inline', headers={'Content-Security-Policy': "sandbox; default-src 'none'"} if item.kind == 'document' else {'Content-Disposition': 'inline'})

    @app.get('/api/v1/uploads/{identifier}/preview')
    async def media_preview(identifier: str, request: Request, actor=AUTH, db=DB):
        import base64
        import os
        initial_company, initial_role = actor.company_id, actor.role
        item = await visible_attachment(db, identifier, actor)
        if item.kind not in ('image', 'audio'):
            problem(415, '此附件不支持媒体预览')
        source = settings.media_dir / item.id
        if not source.is_file():
            problem(404, '附件文件暂不可用')
        path = preview_path(settings, item.id, item.kind)
        data = None
        if not path.is_file():
            if item.kind == 'audio':
                # Browser recordings may lack WebM duration/cues. A WAV preview
                # has a finite duration and supports seeking; keep the original.
                data, _ = await audio_wav(source, settings)
            else:
                result = await image_process(source, 'preview')
                data = base64.b64decode(result['preview']['data'])
        # Conversion runs without a company lock. Authorize again and serialize
        # publication with deletion/permission changes only after it finishes.
        await business.company_lock(db, initial_company)
        current = await db.scalar(select(Member).where(Member.id == actor.id).execution_options(populate_existing=True))
        session_live = await db.scalar(select(Session.id).where(Session.id == request.state.session.id, Session.expires_at > now()))
        if not session_live:
            problem(401, '登录已过期，请重新登录', 'login_required')
        if not current.active or current.company_id != initial_company or current.role != initial_role:
            problem(403, '账号权限已变化，请重新登录')
        item = await visible_attachment(db, identifier, current, lock=True)
        if not (settings.media_dir / item.id).is_file():
            problem(404, '附件文件暂不可用')
        if data is not None and not path.is_file():
            staged = path.with_name(path.name + '.' + str(uuid4()) + '.tmp')
            try:
                with staged.open('xb') as output:
                    os.chmod(staged, 0o600)
                    output.write(data)
                os.replace(staged, path)
            finally:
                staged.unlink(missing_ok=True)
        with path.open('rb') as preview:
            mime = 'audio/wav' if item.kind == 'audio' else 'image/png' if preview.read(8) == b'\x89PNG\r\n\x1a\n' else 'image/jpeg'
        # No browser cache survives a role/ownership change; this URL always authorizes.
        if item.kind == 'audio':
            return FileResponse(path, media_type=mime, headers={'Cache-Control': 'private, no-store', 'Content-Disposition': 'inline'})
        from fastapi.responses import Response
        return Response(path.read_bytes(), media_type=mime, headers={'Cache-Control': 'private, no-store', 'Content-Disposition': 'inline'})

    @app.get('/api/v1/uploads/{identifier}/extraction')
    async def extraction(identifier: str, start: int = Query(0, ge=0, le=2000), limit: int = Query(3, ge=1, le=3), revision: int | None = None, actor=AUTH, db=DB):
        item = await visible_attachment(db, identifier, actor)
        if item.kind != 'document':
            problem(422, '该附件没有文档提取内容')
        if revision is not None and revision != item.extraction_revision:
            problem(409, '文件提取版本已变化，请重新打开来源')
        return await chunk_page(db, item, start, limit)

    @app.post('/api/v1/uploads/{identifier}/retry', status_code=202)
    async def retry_extraction(identifier: str, actor=AUTH, db=DB):
        item = await owned(db, Attachment, identifier, actor, lock=True)
        if item.kind != 'document' or not item.message_id:
            problem(422, '请先发送文档')
        await active_message(db, item.message_id, actor)
        if item.extraction_status != 'failed':
            problem(409, '仅失败文档需要重新解析')
        active = await db.scalar(select(Job.id).where(Job.owner_id == actor.id, Job.target_id.in_([item.id, item.message_id]), Job.state.in_(['queued', 'running'])))
        if active:
            problem(409, '文件正在处理中，请稍后重试')
        item.extraction_status = 'pending'
        job = Job(company_id=actor.company_id, owner_id=actor.id, kind='document', target_id=item.id)
        db.add(job)
        await db.flush()
        return job_dto(job)

    @app.post('/api/v1/messages', status_code=202)
    async def send_message(body: SendMessage, idempotency_key: Annotated[str | None, Header()] = None, actor=AUTH, db=DB):
        payload = body.model_dump()
        if body.voiceCommandAttachmentId is None:
            payload.pop('voiceCommandAttachmentId')
        if not body.newConversation:
            # Keep retries of older clients compatible with their stored digest.
            payload.pop('newConversation')
        prior, digest = await idem_begin(db, actor, 'message', idempotency_key, payload)
        if prior:
            await active_message(db, prior['messageId'], actor)
            return prior
        if body.newConversation:
            conversation = Conversation(company_id=actor.company_id, owner_id=actor.id)
            db.add(conversation)
            await db.flush()
        else:
            conversation = await owned(db, Conversation, body.conversationId, actor, lock=True) if body.conversationId else await default_conversation(db, actor)
        attached = [await owned(db, Attachment, aid, actor, lock=True) for aid in body.attachmentIds]
        if any(a.message_id for a in attached) or sum(a.size for a in attached) > 20 * 1024 * 1024 or sum(a.kind == 'audio' for a in attached) > 1:
            problem(422, '附件已使用或组合不受支持；附件合计最多 4 个、20 MiB，其中最多一段语音')
        if body.voiceCommandAttachmentId is not None and not any(a.id == body.voiceCommandAttachmentId and a.kind == 'audio' for a in attached):
            problem(422, '语音指令必须使用本次发送的语音附件')
        if body.replyTo:
            reply = await active_message(db, body.replyTo, actor)
            await business.require(db, actor, reply.access)
            if reply.conversation_id != conversation.id:
                problem(422, '回复必须属于当前会话')
        item = Message(company_id=actor.company_id, owner_id=actor.id, conversation_id=conversation.id, text=body.text, reply_to=body.replyTo)
        db.add(item)
        await db.flush()
        conversation.updated_at = now()
        if conversation.title == '新会话':
            conversation.title = body.text[:40] or ('文件上报' if attached[0].kind == 'document' else '图片上报' if attached[0].kind == 'image' else '语音上报')
            conversation.revision += 1
        for a in attached:
            a.message_id = item.id
            if a.kind == 'document':
                a.extraction_status = 'pending'
        job = Job(company_id=actor.company_id, owner_id=actor.id, kind='message', target_id=item.id, access=business.scope(actor), result={'attachmentOrder': body.attachmentIds, **({'voiceCommandAttachmentId': body.voiceCommandAttachmentId} if body.voiceCommandAttachmentId else {})})
        db.add(job)
        await db.flush()
        return idem_save(db, actor, 'message', idempotency_key, digest, {'messageId': item.id, 'jobId': job.id, 'conversationId': conversation.id})

    async def list_messages(db, actor, owner_id, cursor, limit, conversation_id=None):
        query = select(Message).where(Message.company_id == actor.company_id, Message.owner_id == owner_id, Message.deleted.is_(False), ~Message.conversation_id.in_(select(Conversation.id).where(Conversation.deleted.is_(True))))
        if conversation_id:
            query = query.where(Message.conversation_id == conversation_id)
        if cursor:
            anchor = await owned(db, Message, cursor, actor, read=True)
            if anchor.owner_id != owner_id or (conversation_id and anchor.conversation_id != conversation_id):
                problem(404, '分页位置不属于当前会话')
            query = query.where((Message.created_at < anchor.created_at) | ((Message.created_at == anchor.created_at) & (Message.id < anchor.id)))
        rows = list((await db.scalars(query.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit + 1))).all())
        return {'items': [await message_dto(db, m, actor) for m in rows[:limit]], 'nextCursor': rows[limit - 1].id if len(rows) > limit else None}

    async def business_link_dtos(db, actor, links):
        items = []
        for link in links:
            try:
                item = await business.source_dto(db, actor, link['evidence'], link['token'])
                items.append({k: v for k, v in item.items() if k not in ('content', 'sourceIds')})
            except HTTPException:
                items.append({'kind': 'business', 'unavailable': True})
        return items

    @app.get('/api/v1/business-sources/{message_id}/{token}')
    async def business_source(message_id: str, token: str, actor=AUTH, db=DB):
        item = await owned(db, Message, message_id, actor)
        await business.require(db, actor, item.access)
        evidence = item.access.get('reads', {}).get(token)
        if not evidence:
            problem(404, '来源不存在或无权查看')
        return await business.source_dto(db, actor, evidence, token)

    @app.get('/api/v1/work-items/{identifier}/business-sources/{token}')
    async def work_business_source(identifier: str, token: str, actor=AUTH, db=DB):
        item = await owned(db, WorkItem, identifier, actor)
        await business.require(db, actor, item.access, retained=True)
        link = next((link for link in item.business_links if link['token'] == token), None)
        if not link:
            problem(404, '来源不存在或无权查看')
        return await business.source_dto(db, actor, link['evidence'], token)

    @app.get('/api/v1/messages')
    async def messages(conversationId: str | None = None, cursor: str | None = None, limit: int = Query(50, ge=1, le=100), actor=AUTH, db=DB):
        if conversationId:
            await owned(db, Conversation, conversationId, actor)
        return await list_messages(db, actor, actor.id, cursor, limit, conversationId)

    @app.get('/api/v1/messages/{identifier}')
    async def get_message(identifier: str, actor=AUTH, db=DB):
        return await message_dto(db, await owned(db, Message, identifier, actor, read=True), actor)

    @app.patch('/api/v1/messages/{identifier}/transcript')
    async def transcript(identifier: str, body: TranscriptEdit, actor=AUTH, db=DB):
        item = await owned(db, Message, identifier, actor, lock=True)
        await active_message(db, identifier, actor)
        if not await db.scalar(select(Attachment.id).where(Attachment.message_id == item.id, Attachment.kind == 'audio')):
            problem(422, '仅语音消息可以修正转写')
        if item.transcript_revision != body.expectedRevision:
            problem(409, '转写已被更新，请读取最新内容')
        item.transcript_history = [*item.transcript_history, {'revision': item.transcript_revision, 'text': item.transcript, 'at': now().isoformat()}]
        item.transcript, item.transcript_revision = body.text, item.transcript_revision + 1
        return await message_dto(db, item, actor)

    @app.get('/api/v1/jobs/{identifier}')
    async def get_job(identifier: str, actor=AUTH, db=DB):
        item = await owned(db, Job, identifier, actor)
        await business.require(db, actor, item.access)
        return job_dto(item)

    @app.get('/api/v1/jobs/{identifier}/feedback')
    async def job_feedback(identifier: str, request: Request, actor=AUTH):
        from .feedback import snapshot
        return await snapshot(sessions, hashlib.sha256(request.cookies.get(COOKIE, '').encode()).hexdigest(), identifier)

    @app.get('/api/v1/jobs/{identifier}/events')
    async def job_events(identifier: str, request: Request, actor=AUTH):
        from .feedback import snapshot, events
        if request.headers.get('origin') not in (None, settings.web_origin) or request.headers.get('sec-fetch-site') == 'cross-site':
            problem(403, '请求来源不被允许')
        token_hash = hashlib.sha256(request.cookies.get(COOKIE, '').encode()).hexdigest()
        await snapshot(sessions, token_hash, identifier)
        return StreamingResponse(events(sessions, token_hash, identifier), media_type='text/event-stream', headers={'Cache-Control':'no-store, no-transform', 'X-Accel-Buffering':'no'})

    @app.post('/api/v1/jobs/{identifier}/retry')
    async def retry(identifier: str, body: RetryJob, actor=AUTH, db=DB):
        item = await owned(db, Job, identifier, actor, lock=True)
        if item.kind == 'document':
            document = await owned(db, Attachment, item.target_id, actor)
            await active_message(db, document.message_id, actor)
        else:
            await active_message(db, item.target_id, actor) if item.kind == 'message' else await owned(db, Report, item.target_id, actor)
        if item.state not in ('failed', 'awaiting_retry'):
            problem(409, '当前任务不需要重试')
        await business.require(db, actor, item.access)
        if item.access and item.access.get('role') != actor.role:
            problem(403, '账号权限已变化，请重新提问')
        item.state, item.error, item.request_started = 'queued', '', False
        if body.useCurrentConfig:
            item.model_binding = None
            item.config_attempt += 1
            if item.kind == 'report':
                item.result = {k: v for k, v in item.result.items() if k != 'reportSaved'}
        item.attempt += 1
        from .feedback import update_feedback
        update_feedback(item, 'queued', '')
        item.updated_at = now()
        return job_dto(item)

    @app.post('/api/v1/work-items', status_code=201)
    async def create_work(body: Progress, idempotency_key: Annotated[str | None, Header()] = None, actor=AUTH, db=DB):
        prior, digest = await idem_begin(db, actor, 'create-work', idempotency_key, body.model_dump(mode='json'))
        if prior:
            item = await owned(db, WorkItem, prior['id'], actor)
            await business.require(db, actor, item.access, retained=True)
            return prior
        item = await writes.save_work(db, actor, body.model_dump(mode='json'))
        return idem_save(db, actor, 'create-work', idempotency_key, digest, work_dto(item))

    @app.get('/api/v1/business-actions')
    async def business_actions(conversationId: str, orphanOnly: bool = False, actor=AUTH, db=DB):
        await owned(db, Conversation, conversationId, actor)
        query = select(BusinessAction).where(BusinessAction.company_id == actor.company_id, BusinessAction.owner_id == actor.id, BusinessAction.conversation_id == conversationId)
        if orphanOnly:
            query = query.where(~exists(select(Message.id).where(Message.id == BusinessAction.message_id, Message.deleted.is_(False))))
        rows = (await db.scalars(query.order_by(BusinessAction.created_at.desc()).limit(80))).all()
        return {'items': [await actions.action_dto(db, actor, row) for row in rows]}

    @app.post('/api/v1/business-actions/{identifier}/{choice}')
    async def confirm_business_action(identifier: str, choice: str, body: Revision, actor=AUTH, db=DB):
        if choice not in ('confirm', 'cancel'):
            problem(404, '操作不存在')
        row = await owned(db, BusinessAction, identifier, actor)
        target_id = row.result.get('objectId') or row.params.get('targetId')
        target = await db.get(Report if row.action.endswith('report') else WorkItem, target_id) if target_id else None
        cleanup_owner = target.owner_id if target and target.company_id == actor.company_id else actor.id
        result = await actions.confirm(db, actor, identifier, body.expectedRevision, cancel=choice == 'cancel')
        await db.commit()
        from .deletion import clean_files
        try:
            await clean_files(db, settings, cleanup_owner)
        except OSError:
            pass  # Persistent attachment tombstones are retried by normal cleanup.
        return result

    @app.get('/api/v1/work-items')
    async def work_items(q: str = Query('', max_length=200), status: str = '', cursor: str | None = None, limit: int = Query(20, ge=1, le=20), actor=AUTH, db=DB):
        from .queries import work_page
        return await work_page(db, actor, actor.id, q, status, cursor, limit)

    @app.get('/api/v1/work-items/{identifier}')
    async def work_item(identifier: str, revision: int | None = Query(None, ge=1), actor=AUTH, db=DB):
        item = await owned(db, WorkItem, identifier, actor, read=True)
        await business.require(db, actor, item.access, retained=True)
        history = (await db.scalars(select(WorkRevision).where(WorkRevision.work_id == item.id).order_by(WorkRevision.revision.desc()).limit(100))).all()
        dto = work_dto(item)
        if revision is not None:
            from .queries import revision_work
            selected = await db.scalar(select(WorkRevision).where(WorkRevision.work_id == item.id, WorkRevision.revision == revision))
            if not selected or not await business.valid(db, actor, selected.access, retained=True):
                problem(404, '工作修订不存在或无权查看')
            dto = revision_work(item, selected)
            history = [row for row in history if row.revision <= revision]
        return {**dto, 'businessLinks': await business_link_dtos(db, actor, selected.business_links if revision is not None else item.business_links), 'history': [{'id': r.id, 'revision': r.revision, 'content': r.content, 'sourceIds': r.source_ids, 'deletedSourceIds': await deleted_sources(db, r.source_ids), 'createdAt': r.created_at.isoformat()} for r in history if await business.valid(db, actor, r.access, retained=True)]}

    @app.patch('/api/v1/progress-drafts/{identifier}')
    async def edit_draft(identifier: str, body: DraftEdit, actor=AUTH, db=DB):
        draft = await owned(db, ProgressDraft, identifier, actor, lock=True)
        message = await active_message(db, draft.message_id, actor)
        await business.require(db, actor, message.access)
        await business.require(db, actor, draft.access)
        version(draft, body.expectedRevision)
        if draft.status != 'pending':
            problem(409, '建议已处理')
        work = await owned(db, WorkItem, body.workId, actor) if body.workId else None
        if work:
            await business.require(db, actor, work.access, retained=True)
        business.inherit(actor, draft, message, *([work] if work else []))
        draft.work_id, draft.base_revision = (work.id, work.revision) if work else (None, None)
        draft.content = {**draft.content, **body.model_dump(mode='json', exclude={'expectedRevision', 'workId'}, exclude_unset=True)}
        draft.revision += 1
        return draft_dto(draft)

    @app.post('/api/v1/progress-drafts/{action}')
    async def process_drafts(action: str, body: Confirm, idempotency_key: Annotated[str | None, Header()] = None, actor=AUTH, db=DB):
        if action not in ('confirm', 'ignore'):
            problem(404, '操作不存在')
        prior, digest = await idem_begin(db, actor, action, idempotency_key, body.model_dump())
        if prior:
            return prior
        work_ids = await confirm_drafts(db, actor, body.items, ignore=action == 'ignore')
        return idem_save(db, actor, action, idempotency_key, digest, {'workIds': work_ids})

    @app.post('/api/v1/work-items/{identifier}/progress')
    async def edit_work(identifier: str, body: WorkEdit, actor=AUTH, db=DB):
        work = await writes.save_work(db, actor, body.model_dump(mode='json', exclude={'expectedRevision', 'sourceIds'}, exclude_unset=True), identifier=identifier, expected=body.expectedRevision, sources=body.sourceIds)
        return work_dto(work)

    @app.get('/api/v1/report-obligations')
    async def report_obligations(kind: str = 'daily', status: str = '', period: date | None = None, cursor: int = Query(0, ge=0), actor=AUTH, db=DB):
        if actor.role != 'employee':
            problem(403, '管理员没有个人汇报待办')
        return await reporting.obligation_page(db, actor, kind=kind, status=status, selected_period=period, cursor=cursor)

    @app.get('/api/v1/team/report-obligations')
    async def team_report_obligations(kind: str = 'daily', status: str = '', period: date | None = None, cursor: int = Query(0, ge=0), actor=ADMIN, db=DB):
        if period is None:
            from zoneinfo import ZoneInfo
            company = await db.get(Company, actor.company_id)
            period = now().astimezone(ZoneInfo(company.rules['timezone'])).date()
        return await reporting.obligation_page(db, actor, kind=kind, status=status, selected_period=period, cursor=cursor, team=True)

    @app.post('/api/v1/report-obligations/{identifier}/prepare')
    async def prepare_obligation(identifier: str, idempotency_key: Annotated[str | None, Header()] = None, actor=AUTH, db=DB):
        prior, digest = await idem_begin(db, actor, 'prepare-obligation:' + identifier, idempotency_key, {})
        if prior:
            return prior
        obligation = await owned(db, ReportObligation, identifier, actor, lock=True)
        if obligation.state == 'cancelled':
            problem(409, '这项汇报安排已撤销')
        report, job = await ensure_report(db, actor, obligation.kind, date.fromisoformat(obligation.period), report_timezone=obligation.timezone)
        obligation.report_id = report.id
        return idem_save(db, actor, 'prepare-obligation:' + identifier, idempotency_key, digest, {'reportId': report.id, 'jobId': job.id})

    @app.get('/api/v1/notifications')
    async def notifications(cursor: int = Query(0, ge=0), actor=AUTH, db=DB):
        if actor.role != 'employee':
            return {'items': [], 'nextCursor': None, 'unread': 0}
        base = select(ReportNotification, ReportObligation).join(ReportObligation, ReportObligation.id == ReportNotification.obligation_id).where(ReportNotification.company_id == actor.company_id, ReportNotification.owner_id == actor.id, ReportObligation.state == 'pending')
        unread = await db.scalar(select(func.count()).select_from(base.where(ReportNotification.read_at.is_(None)).subquery()))
        rows = (await db.execute(base.order_by(ReportNotification.updated_at.desc(), ReportNotification.id).offset(cursor).limit(21))).all()
        return {'items': [{'id': notice.id, 'stage': notice.stage, 'read': notice.read_at is not None, 'updatedAt': notice.updated_at.isoformat(), 'obligation': reporting.obligation_dto(obligation, now(), own=True)} for notice, obligation in rows[:20]], 'nextCursor': str(cursor + 20) if len(rows) > 20 else None, 'unread': unread}

    @app.post('/api/v1/notifications/{identifier}/read')
    async def read_notification(identifier: str, actor=AUTH, db=DB):
        notice = await owned(db, ReportNotification, identifier, actor, lock=True)
        notice.read_at = notice.read_at or now()
        return {'ok': True}

    @app.get('/api/v1/reports')
    async def reports(kind: str = 'daily', cursor: str | None = None, actor=AUTH, db=DB):
        if actor.role != 'employee':
            problem(403, '管理员通过团队查看员工报告')
        query = select(Report).where(Report.deleted.is_(False), Report.owner_id == actor.id, Report.kind == kind)
        if cursor:
            query = query.where(Report.period < cursor)
        rows = (await db.scalars(query.order_by(Report.period.desc()).limit(51))).all()
        return {'items': await report_dtos(db, rows[:50], actor), 'nextCursor': rows[49].period if len(rows) > 50 else None}

    @app.get('/api/v1/reports/{identifier}')
    async def get_report(identifier: str, revision: int | None = Query(None, ge=1), actor=AUTH, db=DB):
        report = await owned(db, Report, identifier, actor, read=True)
        dto = await report_dto(db, report, actor)
        if revision is not None:
            selected = next((row for row in dto['revisions'] if row['revision'] == revision), None)
            if not selected:
                problem(404, '报告修订不存在或无权查看')
            dto.update(content=selected['content'], sourceIds=selected['sourceIds'], revision=revision, publishedRevision=revision, updatedAt=selected['submittedAt'], historical=True)
        return dto

    @app.get('/api/v1/reports/{identifier}/sources')
    async def report_sources(identifier: str, revision: int | None = Query(None, ge=1), actor=AUTH, db=DB):
        report = await owned(db, Report, identifier, actor, read=True)
        dto = await report_dto(db, report, actor)
        if revision is not None and revision != dto['revision']:
            historical = next((row for row in dto['revisions'] if row['revision'] == revision), None)
            if not historical:
                problem(404, '报告修订不存在或无权查看')
            dto = historical
        sources = (await db.scalars(select(WorkRevision).where(WorkRevision.id.in_(dto['sourceIds']), WorkRevision.company_id == actor.company_id, WorkRevision.owner_id == report.owner_id))).all()
        return {'items': [{'id': r.id, 'workId': r.work_id, 'title': r.content['title'], 'revision': r.revision, 'sourceIds': r.source_ids, 'deletedSourceIds': await deleted_sources(db, r.source_ids), 'workDeleted': (await db.get(WorkItem, r.work_id)).deleted} for r in sources]}

    @app.post('/api/v1/reports/generate', status_code=202)
    async def generate_report(body: GenerateReport, idempotency_key: Annotated[str | None, Header()] = None, actor=AUTH, db=DB):
        prior, digest = await idem_begin(db, actor, 'generate-report', idempotency_key, body.model_dump(mode='json'))
        if prior:
            return prior
        report, job = await ensure_report(db, actor, body.kind, body.date)
        return idem_save(db, actor, 'generate-report', idempotency_key, digest, {'reportId': report.id, 'jobId': job.id})

    @app.patch('/api/v1/reports/{identifier}')
    async def edit_report(identifier: str, body: ReportEdit, actor=AUTH, db=DB):
        report = await writes.edit_report(db, actor, identifier, body.expectedRevision, body.content.model_dump())
        return await report_dto(db, report, actor)

    @app.post('/api/v1/reports/{identifier}/candidate')
    async def adopt_candidate(identifier: str, body: Revision, actor=AUTH, db=DB):
        if actor.role != 'employee':
            problem(403, '管理员不编辑个人报告')
        report = await owned(db, Report, identifier, actor, lock=True)
        version(report, body.expectedRevision)
        if not report.candidate:
            problem(409, '没有待采用的生成结果')
        report.content = report.candidate['content']
        report.source_ids = report.candidate['sourceIds']
        report.candidate, report.edited, report.updated_at = None, True, now()
        report.revision += 1
        return await report_dto(db, report, actor)

    @app.post('/api/v1/reports/{identifier}/submit')
    async def submit(identifier: str, body: Revision, idempotency_key: Annotated[str | None, Header()] = None, actor=AUTH, db=DB):
        if actor.role != 'employee':
            problem(403, '管理员不提交个人报告')
        action = f'submit:{identifier}'
        prior, digest = await idem_begin(db, actor, action, idempotency_key, body.model_dump())
        if prior:
            return prior
        report = await writes.submit_report(db, actor, identifier, body.expectedRevision)
        return idem_save(db, actor, action, idempotency_key, digest, {'ok': True, 'revision': report.revision})

    @app.get('/api/v1/settings/report-rules')
    async def get_rules(actor=AUTH, db=DB):
        company = await db.get(Company, actor.company_id)
        return {**company.rules, 'revision': company.revision, 'effectivePeriods': await reporting.effective_periods(db, company)}

    @app.put('/api/v1/settings/report-rules')
    async def save_rules(body: Rules, actor=ADMIN, db=DB):
        company = await db.scalar(select(Company).where(Company.id == actor.company_id).with_for_update())
        version(company, body.expectedRevision)
        company.rules, company.rules_effective_at = body.model_dump(exclude={'expectedRevision'}), now()
        company.revision += 1
        await reporting.save_schedule(db, company)
        return {**company.rules, 'revision': company.revision, 'effectivePeriods': await reporting.effective_periods(db, company)}

    @app.get('/api/v1/settings/model-usage')
    async def model_usage(period: str = 'this_week', start: date | None = None, end: date | None = None, service: str = Query('', max_length=36), model: str = Query('', max_length=200), purpose: str = Query('', max_length=16), cursor: str | None = None, limit: int = Query(20, ge=1, le=20), actor=ADMIN, db=DB):
        from .usage import usage_page
        return await usage_page(db, actor, period=period, start=start, end=end, service=service, model=model, purpose=purpose, cursor=cursor, limit=limit)

    @app.get('/api/v1/team')
    async def team(period: str = 'this_week', start: date | None = None, end: date | None = None, q: str = Query('', max_length=200), status: str = '', members: str = 'active', actor=ADMIN, db=DB):
        from .queries import team_data
        summary, _ = await team_data(db, actor, period=period, start=start, end=end, q=q, status=status, members=members)
        return summary

    @app.get('/api/v1/team/details')
    async def team_details(metric: str, period: str = 'this_week', start: date | None = None, end: date | None = None, q: str = Query('', max_length=200), status: str = '', members: str = 'active', cursor: str | None = None, limit: int = Query(20, ge=1, le=20), actor=ADMIN, db=DB):
        from .queries import team_data, detail_page
        if metric not in ('messages', 'blocked', 'reports'):
            problem(422, '统计指标无效')
        summary, details = await team_data(db, actor, period=period, start=start, end=end, q=q, status=status, members=members)
        return {**detail_page(details[metric], cursor, limit), 'range': summary['range'], 'metrics': summary['metrics'], 'total': len(details[metric])}

    @app.get('/api/v1/team/members/{identifier}/messages')
    async def team_messages(identifier: str, cursor: str | None = None, limit: int = Query(50, ge=1, le=100), actor=ADMIN, db=DB):
        await visible_member(db, actor, identifier, employee_only=True)
        return await list_messages(db, actor, identifier, cursor, limit)

    @app.get('/api/v1/team/members/{identifier}/work')
    async def team_work(identifier: str, q: str = Query('', max_length=200), status: str = '', cursor: str | None = None, limit: int = Query(20, ge=1, le=20), actor=ADMIN, db=DB):
        from .queries import work_page
        member = await visible_member(db, actor, identifier, employee_only=True)
        return {'member': member_dto(member), **await work_page(db, actor, identifier, q, status, cursor, limit)}

    @app.get('/api/v1/team/members/{identifier}/reports')
    async def team_reports(identifier: str, kind: str = 'daily', cursor: str | None = None, actor=ADMIN, db=DB):
        await visible_member(db, actor, identifier, employee_only=True)
        query = select(Report).where(Report.deleted.is_(False), Report.owner_id == identifier, Report.kind == kind, Report.published_revision > 0)
        if cursor:
            query = query.where(Report.period < cursor)
        rows = (await db.scalars(query.order_by(Report.period.desc()).limit(51))).all()
        return {'items': await report_dtos(db, rows[:50], actor), 'nextCursor': rows[49].period if len(rows) > 50 else None}

    async def deleted_sources(db, ids):
        available = set((await db.scalars(select(Message.id).where(Message.id.in_(ids), Message.deleted.is_(False)))).all())
        return [identifier for identifier in ids if identifier not in available]

    @app.get('/api/v1/conversations')
    async def conversations(q: str = Query('', max_length=120), cursor: str | None = None, actor=AUTH, db=DB):
        query = select(Conversation).where(Conversation.owner_id == actor.id, Conversation.company_id == actor.company_id, Conversation.deleted.is_(False))
        if q.strip():
            query = query.where(Conversation.title.icontains(q.strip(), autoescape=True))
        if cursor:
            anchor = await owned(db, Conversation, cursor, actor)
            query = query.where((Conversation.updated_at < anchor.updated_at) | ((Conversation.updated_at == anchor.updated_at) & (Conversation.id < anchor.id)))
        rows = list((await db.scalars(query.order_by(Conversation.updated_at.desc(), Conversation.id.desc()).limit(51))).all())
        return {'items': [conversation_dto(row) for row in rows[:50]], 'nextCursor': rows[49].id if len(rows) > 50 else None}

    @app.post('/api/v1/conversations', status_code=201)
    async def add_conversation(body: ConversationCreate, actor=AUTH, db=DB):
        if not body.title.strip():
            problem(422, '请输入会话名称')
        item = Conversation(company_id=actor.company_id, owner_id=actor.id, title=body.title.strip())
        db.add(item)
        await db.flush()
        return conversation_dto(item)

    @app.get('/api/v1/conversations/{identifier}')
    async def get_conversation(identifier: str, actor=AUTH, db=DB):
        return conversation_dto(await owned(db, Conversation, identifier, actor))

    @app.patch('/api/v1/conversations/{identifier}')
    async def rename_conversation(identifier: str, body: ConversationEdit, actor=AUTH, db=DB):
        item = await owned(db, Conversation, identifier, actor, lock=True)
        version(item, body.expectedRevision)
        if not body.title.strip():
            problem(422, '请输入会话名称')
        item.title, item.revision = body.title.strip(), item.revision + 1
        return conversation_dto(item)

    @app.get('/api/v1/conversations/{identifier}/deletion')
    async def conversation_deletion(identifier: str, actor=AUTH, db=DB):
        from .deletion import conversation_impact
        item = await owned(db, Conversation, identifier, actor)
        messages, retained = await conversation_impact(db, item)
        return {'messages': len(messages), 'retainedSources': len(retained)}

    async def finish_deletion(db, owner_id):
        from .deletion import clean_files
        # Commit the durable tombstones before touching files. A failed cleanup
        # remains hidden, is retried by maintenance and by the same DELETE URL.
        await db.commit()
        try:
            await clean_files(db, settings, owner_id)
        except OSError:
            problem(503, '记录已移除，附件清理尚未完成，请重试删除', 'cleanup_pending')
        return {'ok': True}

    @app.delete('/api/v1/conversations/{identifier}')
    async def delete_conversation(identifier: str, body: Revision, actor=AUTH, db=DB):
        from .deletion import target, remove_conversation
        item = await target(db, Conversation, identifier, actor, body.expectedRevision)
        await remove_conversation(db, item)
        return await finish_deletion(db, item.owner_id)

    @app.delete('/api/v1/work-items/{identifier}')
    async def delete_work(identifier: str, body: Revision, actor=AUTH, db=DB):
        item = await writes.remove_record(db, actor, 'work', identifier, body.expectedRevision)
        return await finish_deletion(db, item.owner_id)

    @app.get('/api/v1/reports/{identifier}/deletion')
    async def report_deletion(identifier: str, actor=AUTH, db=DB):
        item = await owned(db, Report, identifier, actor, read=True)
        impact = await writes.deletion_impact(db, item, actor)
        return {key: impact[key] for key in ('messages', 'attachments', 'revision')}

    @app.delete('/api/v1/reports/{identifier}')
    async def delete_report(identifier: str, body: Revision, actor=AUTH, db=DB):
        item = await writes.remove_record(db, actor, 'report', identifier, body.expectedRevision)
        return await finish_deletion(db, item.owner_id)

    return app


app = create_app()

if __name__ == '__main__':
    import uvicorn
    uvicorn.run('paa_server.api:app', host='127.0.0.1', port=8000)
