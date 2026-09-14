import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
import hashlib
import secrets
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pwdlib import PasswordHash
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from .documents import attachment_dto, chunk_page, document_type, safe_name, visible_attachment
from .config import Settings
from .db import database
from .media import audio_mime, audio_wav, image_input
from .models import Conversation, Attachment, Company, Job, LoginAttempt, Member, Message, ProgressDraft, Report, ReportRevision, Session, WorkItem, WorkRevision, now
from .model_schemas import RetryJob
from .model_provider import ProviderError
from .model_secrets import SecretUnavailable
from .schemas import ConversationCreate, ConversationEdit, Confirm, DraftEdit, GenerateReport, Login, MemberCreate, MemberPatch, Password, ReportEdit, ResetPassword, Revision, Rules, SendMessage, TranscriptEdit, WorkEdit
from .service import active_message, conversation_dto, default_conversation, confirm_drafts, draft_dto, ensure_report, idem_begin, idem_save, job_dto, member_dto, owned, problem, version, work_dto

passwords = PasswordHash.recommended()
DUMMY_PASSWORD = passwords.hash('constant-not-a-login-password')
COOKIE = 'paa_company_session'


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

    @app.middleware('http')
    async def boundaries(request, call_next):
        request.state.request_id = str(uuid4())
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('origin') != settings.web_origin:
            return JSONResponse({'error': {'code': 'origin_rejected', 'message': '请求来源不被允许', 'requestId': request.state.request_id}}, status_code=403)
        try:
            response = await call_next(request)
        except SQLAlchemyError:
            response = JSONResponse({'error': {'code': 'service_unavailable', 'message': '服务暂不可用，请稍后重试', 'requestId': request.state.request_id}}, status_code=503)
        response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'same-origin', 'X-Request-ID': request.state.request_id})
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        detail = error.detail if isinstance(error.detail, dict) else {'code': 'invalid_request', 'message': str(error.detail)}
        return JSONResponse({'error': {**detail, 'requestId': request.state.request_id}}, status_code=error.status_code)

    @app.exception_handler(ProviderError)
    @app.exception_handler(SecretUnavailable)
    async def model_error(request, error):
        return JSONResponse({'error': {'code': getattr(error, 'code', 'secret_unavailable'), 'message': str(error), 'requestId': request.state.request_id}}, status_code=422 if isinstance(error, ProviderError) else 503)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse({'error': {'code': 'validation_error', 'message': '请检查输入内容、日期和长度限制', 'requestId': request.state.request_id, 'fields': ['.'.join(map(str, e['loc'])) for e in error.errors()]}}, status_code=422)

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
        if actor is None or not actor.active:
            problem(401, '登录已过期，请重新登录', 'login_required')
        if request.method not in ('GET', 'HEAD') and not secrets.compare_digest(request.headers.get('x-csrf-token', ''), session.csrf):
            problem(403, '请求校验失败，请刷新后重试', 'csrf_rejected')
        if actor.must_change_password and request.url.path not in ('/api/v1/auth/me', '/api/v1/auth/password', '/api/v1/auth/logout'):
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

    async def visible_member(db, actor, member_id, *, employee_only=False):
        target = await db.scalar(select(Member).where(Member.id == member_id, Member.company_id == actor.company_id))
        if target is None or (employee_only and target.role != 'employee') or (actor.role != 'admin' and actor.id != target.id):
            problem(404, '成员不存在或无权查看')
        return target

    async def message_dto(db, item, actor):
        attachments = (await db.scalars(select(Attachment).where(Attachment.message_id == item.id, Attachment.deleted.is_(False)))).all()
        job = await db.scalar(select(Job).where(Job.target_id == item.id, Job.kind == 'message').order_by(Job.created_at.desc()).limit(1))
        private = (await db.scalars(select(ProgressDraft).where(ProgressDraft.message_id == item.id, ProgressDraft.status != 'deleted').order_by(ProgressDraft.created_at))).all() if actor.id == item.owner_id else []
        statuses = {d.id: d.status for d in (await db.scalars(select(ProgressDraft).where(ProgressDraft.message_id == item.id))).all()}
        return {'id': item.id, 'ownerId': item.owner_id, 'conversationId': item.conversation_id, 'text': item.text, 'reply': item.reply, 'citations': item.citations, 'replyTo': item.reply_to, 'transcript': item.transcript, 'transcriptRevision': item.transcript_revision, 'createdAt': item.created_at.isoformat(), 'attachments': [attachment_dto(a) for a in attachments], 'job': job_dto(job) if job else None, 'drafts': [draft_dto(d) for d in private], 'suggestions': [{**s, 'status': statuses.get(s['id'], 'pending')} for s in item.suggestions]}

    async def report_dto(db, report, actor):
        revisions = list((await db.scalars(select(ReportRevision).where(ReportRevision.report_id == report.id).order_by(ReportRevision.revision.desc()))).all())
        own = actor.id == report.owner_id
        if not own and not revisions:
            problem(404, '报告尚未提交或无权查看')
        job = await db.scalar(select(Job).where(Job.target_id == report.id, Job.kind == 'report').order_by(Job.created_at.desc()).limit(1)) if own else None
        public = revisions[0] if revisions else None
        return {'id': report.id, 'ownerId': report.owner_id, 'kind': report.kind, 'period': report.period, 'periodEnd': report.period_end, 'timezone': report.timezone, 'content': report.content if own else public.content, 'candidate': report.candidate if own else None, 'sourceIds': report.source_ids if own else public.source_ids, 'revision': report.revision if own else public.revision, 'publishedRevision': report.published_revision, 'managementRevision': report.revision, 'updatedAt': (report.updated_at if own else public.created_at).isoformat(), 'job': job_dto(job) if job else None, 'revisions': [{'revision': r.revision, 'content': r.content, 'sourceIds': r.source_ids, 'submittedAt': r.created_at.isoformat()} for r in revisions]}

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
        valid = await run_in_threadpool(passwords.verify, body.password, actor.password_hash if actor else DUMMY_PASSWORD)
        if not valid or actor is None or not actor.active:
            db.add(LoginAttempt(identity=ident))
            await db.commit()
            problem(401, '账号或密码不正确')
        await db.execute(delete(LoginAttempt).where(LoginAttempt.identity == ident))
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        db.add(Session(member_id=actor.id, token_hash=hashlib.sha256(token.encode()).hexdigest(), csrf=csrf, expires_at=now() + timedelta(hours=8)))
        response.set_cookie(COOKIE, token, httponly=True, secure=settings.cookie_secure, samesite='lax', max_age=8*3600, path='/')
        company = await db.get(Company, actor.company_id)
        return {'member': member_dto(actor), 'csrf': csrf, 'company': {'id': company.id, 'name': company.name}}

    @app.get('/api/v1/auth/me')
    async def me(request: Request, actor=AUTH, db=DB):
        company = await db.get(Company, actor.company_id)
        return {'member': member_dto(actor), 'csrf': request.state.session.csrf, 'company': {'id': company.id, 'name': company.name}}

    @app.post('/api/v1/auth/logout')
    async def logout(response: Response, request: Request, actor=AUTH, db=DB):
        await db.delete(request.state.session)
        response.delete_cookie(COOKIE, path='/')
        return {'ok': True}

    @app.post('/api/v1/auth/password')
    async def password(body: Password, response: Response, actor=AUTH, db=DB):
        if not await run_in_threadpool(passwords.verify, body.currentPassword, actor.password_hash):
            problem(400, '当前密码不正确')
        actor.password_hash = await run_in_threadpool(passwords.hash, body.newPassword)
        actor.must_change_password = False
        await db.execute(delete(Session).where(Session.member_id == actor.id))
        response.delete_cookie(COOKIE, path='/')
        return {'ok': True}

    @app.get('/api/v1/members')
    async def members(actor=ADMIN, db=DB):
        return {'items': [member_dto(m) for m in (await db.scalars(select(Member).where(Member.company_id == actor.company_id, Member.role == 'employee').order_by(Member.created_at))).all()]}

    @app.post('/api/v1/members', status_code=201)
    async def add_member(body: MemberCreate, actor=ADMIN, db=DB):
        if body.role != 'employee':
            problem(403, '成员管理仅可添加员工')
        if await db.scalar(select(Member.id).where(Member.username == body.username.lower())):
            problem(409, '账号名称已被使用')
        item = Member(company_id=actor.company_id, username=body.username.lower(), name=body.name, role=body.role, password_hash=await run_in_threadpool(passwords.hash, body.password))
        db.add(item)
        await db.flush()
        return member_dto(item)

    @app.patch('/api/v1/members/{identifier}')
    async def change_member(identifier: str, body: MemberPatch, actor=ADMIN, db=DB):
        await db.scalar(select(Company).where(Company.id == actor.company_id).with_for_update())
        item = await visible_member(db, actor, identifier, employee_only=True)
        item.active = body.active
        if not item.active:
            await db.execute(delete(Session).where(Session.member_id == item.id))
        return member_dto(item)

    @app.post('/api/v1/members/{identifier}/reset-password')
    async def reset_password(identifier: str, body: ResetPassword, actor=ADMIN, db=DB):
        item = await visible_member(db, actor, identifier, employee_only=True)
        item.password_hash = await run_in_threadpool(passwords.hash, body.password)
        item.must_change_password = True
        await db.execute(delete(Session).where(Session.member_id == item.id))
        return {'ok': True}

    @app.post('/api/v1/uploads', status_code=201)
    async def upload(file: UploadFile, actor=AUTH, db=DB):
        name = safe_name(file.filename)
        mime = document_type(name, file.content_type)
        suffix = Path(name).suffix.lower()
        kind = 'document' if mime else 'image' if (file.content_type or '').startswith('image/') or suffix in ('.jpg', '.jpeg', '.png', '.webp') else 'audio'
        if kind != 'image' and not mime and not ((file.content_type or '').startswith(('audio/', 'image/')) or Path(name).suffix.lower() in ('.m4a', '.wav', '.webm', '.mp4', '.aac')):
            problem(415, '请使用 PDF、DOCX、PPTX、TXT、JSON、MD、CSV、图片或语音文件')
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
            duration = None
            if kind == 'image':
                mime, _ = await run_in_threadpool(image_input, await run_in_threadpool(path.read_bytes))
            elif kind == 'audio':
                with path.open('rb') as raw:
                    mime = audio_mime(raw.read(16))
                _, duration = await audio_wav(path, settings)
            elif Path(name).suffix.lower() in ('.pdf', '.docx', '.pptx'):
                with path.open('rb') as raw:
                    magic = raw.read(8)
                if not (magic.startswith(b'%PDF-') if name.lower().endswith('.pdf') else magic.startswith(b'PK')):
                    problem(415, '文件结构与扩展名不符或文件已损坏，请重新导出')
            item = Attachment(id=identifier, company_id=actor.company_id, owner_id=actor.id, kind=kind, mime=mime, name=name, size=size, sha256=digest.hexdigest(), duration=duration, extraction_status='unsent' if kind == 'document' else 'none')
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
        prior, digest = await idem_begin(db, actor, 'message', idempotency_key, body.model_dump())
        if prior:
            await active_message(db, prior['messageId'], actor)
            return prior
        conversation = await owned(db, Conversation, body.conversationId, actor, lock=True) if body.conversationId else await default_conversation(db, actor)
        attached = [await owned(db, Attachment, aid, actor, lock=True) for aid in body.attachmentIds]
        if any(a.message_id for a in attached) or (any(a.kind == 'audio' for a in attached) and len(attached) != 1) or sum(a.size for a in attached) > 20 * 1024 * 1024 or sum(a.kind == 'audio' for a in attached) > 1:
            problem(422, '附件已使用或组合不受支持；文档与图片合计最多 4 个、20 MiB，语音单独发送')
        if body.replyTo:
            reply = await active_message(db, body.replyTo, actor)
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
        job = Job(company_id=actor.company_id, owner_id=actor.id, kind='message', target_id=item.id)
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
        return job_dto(await owned(db, Job, identifier, actor))

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
        item.state, item.error, item.request_started = 'queued', '', False
        if body.useCurrentConfig:
            item.model_binding = None
            item.config_attempt += 1
            if item.kind == 'report':
                item.result = {k: v for k, v in item.result.items() if k != 'reportSaved'}
        item.attempt += 1
        item.updated_at = now()
        return job_dto(item)

    @app.get('/api/v1/work-items')
    async def work_items(actor=AUTH, db=DB):
        return {'items': [work_dto(w) for w in (await db.scalars(select(WorkItem).where(WorkItem.deleted.is_(False), WorkItem.owner_id == actor.id).order_by(WorkItem.updated_at.desc()).limit(100))).all()]}

    @app.get('/api/v1/work-items/{identifier}')
    async def work_item(identifier: str, actor=AUTH, db=DB):
        item = await owned(db, WorkItem, identifier, actor, read=True)
        history = (await db.scalars(select(WorkRevision).where(WorkRevision.work_id == item.id).order_by(WorkRevision.revision.desc()).limit(100))).all()
        return {**work_dto(item), 'history': [{'id': r.id, 'revision': r.revision, 'content': r.content, 'sourceIds': r.source_ids, 'deletedSourceIds': await deleted_sources(db, r.source_ids), 'createdAt': r.created_at.isoformat()} for r in history]}

    @app.patch('/api/v1/progress-drafts/{identifier}')
    async def edit_draft(identifier: str, body: DraftEdit, actor=AUTH, db=DB):
        draft = await owned(db, ProgressDraft, identifier, actor, lock=True)
        await active_message(db, draft.message_id, actor)
        version(draft, body.expectedRevision)
        if draft.status != 'pending':
            problem(409, '建议已处理')
        work = await owned(db, WorkItem, body.workId, actor) if body.workId else None
        draft.work_id, draft.base_revision = (work.id, work.revision) if work else (None, None)
        draft.content = body.model_dump(exclude={'expectedRevision', 'workId'})
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
        work = await owned(db, WorkItem, identifier, actor, lock=True)
        version(work, body.expectedRevision)
        for source in body.sourceIds:
            await owned(db, Message, source, actor)
        work.content = body.model_dump(exclude={'expectedRevision', 'sourceIds'})
        work.title, work.revision, work.updated_at = body.title, work.revision + 1, now()
        db.add(WorkRevision(company_id=actor.company_id, owner_id=actor.id, work_id=work.id, revision=work.revision, content=work.content, source_ids=body.sourceIds))
        return work_dto(work)

    @app.get('/api/v1/reports')
    async def reports(kind: str = 'daily', cursor: str | None = None, actor=AUTH, db=DB):
        if actor.role != 'employee':
            problem(403, '管理员通过团队查看员工报告')
        query = select(Report).where(Report.deleted.is_(False), Report.owner_id == actor.id, Report.kind == kind)
        if cursor:
            query = query.where(Report.period < cursor)
        rows = (await db.scalars(query.order_by(Report.period.desc()).limit(51))).all()
        return {'items': [await report_dto(db, r, actor) for r in rows[:50]], 'nextCursor': rows[49].period if len(rows) > 50 else None}

    @app.get('/api/v1/reports/{identifier}')
    async def get_report(identifier: str, actor=AUTH, db=DB):
        return await report_dto(db, await owned(db, Report, identifier, actor, read=True), actor)

    @app.get('/api/v1/reports/{identifier}/sources')
    async def report_sources(identifier: str, actor=AUTH, db=DB):
        report = await owned(db, Report, identifier, actor, read=True)
        dto = await report_dto(db, report, actor)
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
        if actor.role != 'employee':
            problem(403, '管理员不编辑个人报告')
        report = await owned(db, Report, identifier, actor, lock=True)
        version(report, body.expectedRevision)
        report.content, report.edited, report.updated_at = body.content.model_dump(), True, now()
        report.revision += 1
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
        report = await owned(db, Report, identifier, actor, lock=True)
        version(report, body.expectedRevision)
        if report.published_revision == report.revision:
            problem(409, '这一版本已经提交')
        if not any(str(v).strip() for v in report.content.values()):
            problem(422, '请先填写报告内容')
        db.add(ReportRevision(company_id=actor.company_id, owner_id=actor.id, report_id=report.id, revision=report.revision, content=report.content, source_ids=report.source_ids))
        report.published_revision, report.updated_at = report.revision, now()
        return idem_save(db, actor, action, idempotency_key, digest, {'ok': True, 'revision': report.revision})

    @app.get('/api/v1/settings/report-rules')
    async def get_rules(actor=AUTH, db=DB):
        company = await db.get(Company, actor.company_id)
        return {**company.rules, 'revision': company.revision}

    @app.put('/api/v1/settings/report-rules')
    async def save_rules(body: Rules, actor=ADMIN, db=DB):
        company = await db.scalar(select(Company).where(Company.id == actor.company_id).with_for_update())
        version(company, body.expectedRevision)
        company.rules, company.rules_effective_at = body.model_dump(exclude={'expectedRevision'}), now()
        company.revision += 1
        return {**company.rules, 'revision': company.revision}

    @app.get('/api/v1/team')
    async def team(start: date | None = None, end: date | None = None, status: str = '', actor=ADMIN, db=DB):
        from zoneinfo import ZoneInfo
        company = await db.get(Company, actor.company_id)
        zone = ZoneInfo(company.rules['timezone'])
        if start and end and start > end:
            problem(422, '开始日期不能晚于结束日期')
        people = (await db.scalars(select(Member).where(Member.company_id == actor.company_id, Member.role == 'employee').order_by(Member.created_at))).all()
        result = []
        for member in people:
            query = select(WorkItem).where(WorkItem.deleted.is_(False), WorkItem.owner_id == member.id)
            if status:
                query = query.where(WorkItem.content['status'].astext == status)
            if start:
                query = query.where(WorkItem.updated_at >= datetime.combine(start, datetime.min.time(), zone))
            if end:
                query = query.where(WorkItem.updated_at < datetime.combine(end, datetime.min.time(), zone) + timedelta(days=1))
            work = (await db.scalars(query.order_by(WorkItem.updated_at.desc()).limit(100))).all()
            last = await db.scalar(select(func.max(Message.created_at)).where(Message.owner_id == member.id, Message.deleted.is_(False)))
            report_count = await db.scalar(select(func.count()).select_from(Report).where(Report.owner_id == member.id, Report.deleted.is_(False), Report.published_revision > 0))
            result.append({'member': member_dto(member), 'work': [work_dto(w) for w in work], 'lastMessageAt': last.isoformat() if last else None, 'reportCount': report_count})
        return {'items': result, 'updatedAt': now().isoformat()}

    @app.get('/api/v1/team/members/{identifier}/messages')
    async def team_messages(identifier: str, cursor: str | None = None, limit: int = Query(50, ge=1, le=100), actor=ADMIN, db=DB):
        await visible_member(db, actor, identifier, employee_only=True)
        return await list_messages(db, actor, identifier, cursor, limit)

    @app.get('/api/v1/team/members/{identifier}/work')
    async def team_work(identifier: str, actor=ADMIN, db=DB):
        member = await visible_member(db, actor, identifier, employee_only=True)
        return {'member': member_dto(member), 'items': [work_dto(w) for w in (await db.scalars(select(WorkItem).where(WorkItem.deleted.is_(False), WorkItem.owner_id == identifier).order_by(WorkItem.updated_at.desc()).limit(100))).all()]}

    @app.get('/api/v1/team/members/{identifier}/reports')
    async def team_reports(identifier: str, kind: str = 'daily', cursor: str | None = None, actor=ADMIN, db=DB):
        await visible_member(db, actor, identifier, employee_only=True)
        query = select(Report).where(Report.deleted.is_(False), Report.owner_id == identifier, Report.kind == kind, Report.published_revision > 0)
        if cursor:
            query = query.where(Report.period < cursor)
        rows = (await db.scalars(query.order_by(Report.period.desc()).limit(51))).all()
        return {'items': [await report_dto(db, r, actor) for r in rows[:50]], 'nextCursor': rows[49].period if len(rows) > 50 else None}

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
        from .deletion import target, remove_work
        item = await target(db, WorkItem, identifier, actor, body.expectedRevision)
        await remove_work(db, item)
        return await finish_deletion(db, item.owner_id)

    @app.get('/api/v1/reports/{identifier}/deletion')
    async def report_deletion(identifier: str, actor=AUTH, db=DB):
        item = await owned(db, Report, identifier, actor, read=True)
        if actor.role != 'admin' and item.published_revision:
            problem(403, '已提交的报告不能删除')
        revisions = (await db.scalars(select(ReportRevision).where(ReportRevision.report_id == item.id))).all()
        ids = set(item.source_ids) | set((item.candidate or {}).get('sourceIds', []))
        for revision in revisions:
            ids.update(revision.source_ids)
        sources = (await db.scalars(select(WorkRevision).where(WorkRevision.id.in_(ids), WorkRevision.owner_id == item.owner_id))).all()
        messages = {mid for source in sources for mid in source.source_ids}
        count = await db.scalar(select(func.count()).select_from(Message).where(Message.id.in_(messages), Message.deleted.is_(False), Message.owner_id == item.owner_id))
        attachments = await db.scalar(select(func.count()).select_from(Attachment).where(Attachment.message_id.in_(messages), Attachment.deleted.is_(False), Attachment.owner_id == item.owner_id))
        return {'messages': count if actor.role == 'admin' else 0, 'attachments': attachments if actor.role == 'admin' else 0, 'revision': item.revision}

    @app.delete('/api/v1/reports/{identifier}')
    async def delete_report(identifier: str, body: Revision, actor=AUTH, db=DB):
        from .deletion import target, remove_report
        item = await target(db, Report, identifier, actor, body.expectedRevision)
        await remove_report(db, item, actor)
        return await finish_deletion(db, item.owner_id)

    return app


app = create_app()

if __name__ == '__main__':
    import uvicorn
    uvicorn.run('paa_server.api:app', host='127.0.0.1', port=8000)
