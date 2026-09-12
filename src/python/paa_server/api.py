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

from .config import Settings
from .db import database
from .media import audio_mime, audio_wav, checksum, image_input
from .models import Attachment, Company, Job, LoginAttempt, Member, Message, ProgressDraft, Report, ReportRevision, Session, WorkItem, WorkRevision, now
from .schemas import Confirm, DraftEdit, GenerateReport, Login, MemberCreate, MemberPatch, Password, ReportEdit, ResetPassword, Revision, Rules, SendMessage, TranscriptEdit, WorkEdit
from .service import confirm_drafts, draft_dto, ensure_report, idem_begin, idem_save, job_dto, member_dto, owned, problem, version, work_dto

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

    DB = Depends(db_dep)

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

    async def visible_member(db, actor, member_id, *, employee_only=False):
        target = await db.scalar(select(Member).where(Member.id == member_id, Member.company_id == actor.company_id))
        if target is None or (employee_only and target.role != 'employee') or (actor.role != 'admin' and actor.id != target.id):
            problem(404, '成员不存在或无权查看')
        return target

    async def message_dto(db, item, actor):
        attachments = (await db.scalars(select(Attachment).where(Attachment.message_id == item.id))).all()
        job = await db.scalar(select(Job).where(Job.target_id == item.id, Job.kind == 'message').order_by(Job.created_at.desc()).limit(1))
        private = (await db.scalars(select(ProgressDraft).where(ProgressDraft.message_id == item.id).order_by(ProgressDraft.created_at))).all() if actor.id == item.owner_id else []
        statuses = {d.id: d.status for d in (await db.scalars(select(ProgressDraft).where(ProgressDraft.message_id == item.id))).all()}
        return {'id': item.id, 'ownerId': item.owner_id, 'text': item.text, 'reply': item.reply, 'replyTo': item.reply_to, 'transcript': item.transcript, 'transcriptRevision': item.transcript_revision, 'createdAt': item.created_at.isoformat(), 'attachments': [attachment_dto(a) for a in attachments], 'job': job_dto(job) if job else None, 'drafts': [draft_dto(d) for d in private], 'suggestions': [{**s, 'status': statuses.get(s['id'], 'pending')} for s in item.suggestions]}

    def attachment_dto(a):
        return {'id': a.id, 'kind': a.kind, 'name': a.name, 'size': a.size, 'mime': a.mime, 'duration': a.duration, 'url': f'/api/v1/uploads/{a.id}/content'}

    async def report_dto(db, report, actor):
        revisions = list((await db.scalars(select(ReportRevision).where(ReportRevision.report_id == report.id).order_by(ReportRevision.revision.desc()))).all())
        own = actor.id == report.owner_id
        if not own and not revisions:
            problem(404, '报告尚未提交或无权查看')
        job = await db.scalar(select(Job).where(Job.target_id == report.id, Job.kind == 'report').order_by(Job.created_at.desc()).limit(1)) if own else None
        public = revisions[0] if revisions else None
        return {'id': report.id, 'ownerId': report.owner_id, 'kind': report.kind, 'period': report.period, 'periodEnd': report.period_end, 'timezone': report.timezone, 'content': report.content if own else public.content, 'candidate': report.candidate if own else None, 'sourceIds': report.source_ids if own else public.source_ids, 'revision': report.revision if own else public.revision, 'publishedRevision': report.published_revision, 'updatedAt': (report.updated_at if own else public.created_at).isoformat(), 'job': job_dto(job) if job else None, 'revisions': [{'revision': r.revision, 'content': r.content, 'sourceIds': r.source_ids, 'submittedAt': r.created_at.isoformat()} for r in revisions]}

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
        return {'items': [member_dto(m) for m in (await db.scalars(select(Member).where(Member.company_id == actor.company_id).order_by(Member.created_at))).all()]}

    @app.post('/api/v1/members', status_code=201)
    async def add_member(body: MemberCreate, actor=ADMIN, db=DB):
        if await db.scalar(select(Member.id).where(Member.username == body.username.lower())):
            problem(409, '账号名称已被使用')
        item = Member(company_id=actor.company_id, username=body.username.lower(), name=body.name, role=body.role, password_hash=await run_in_threadpool(passwords.hash, body.password))
        db.add(item)
        await db.flush()
        return member_dto(item)

    @app.patch('/api/v1/members/{identifier}')
    async def change_member(identifier: str, body: MemberPatch, actor=ADMIN, db=DB):
        await db.scalar(select(Company).where(Company.id == actor.company_id).with_for_update())
        item = await visible_member(db, actor, identifier)
        if not body.active and item.role == 'admin':
            count = await db.scalar(select(func.count()).select_from(Member).where(Member.company_id == actor.company_id, Member.role == 'admin', Member.active.is_(True)))
            if count <= 1 and item.active:
                problem(409, '不能停用最后一名有效管理员')
        item.active = body.active
        if not item.active:
            await db.execute(delete(Session).where(Session.member_id == item.id))
        return member_dto(item)

    @app.post('/api/v1/members/{identifier}/reset-password')
    async def reset_password(identifier: str, body: ResetPassword, actor=ADMIN, db=DB):
        item = await visible_member(db, actor, identifier)
        item.password_hash = await run_in_threadpool(passwords.hash, body.password)
        item.must_change_password = True
        await db.execute(delete(Session).where(Session.member_id == item.id))
        return {'ok': True}

    @app.post('/api/v1/uploads', status_code=201)
    async def upload(file: UploadFile, actor=AUTH, db=DB):
        data = await file.read(20 * 1024 * 1024 + 1)
        if len(data) > 20 * 1024 * 1024:
            problem(413, '文件不能超过 20 MiB')
        if not data:
            problem(422, '不能上传空文件')
        kind = 'image' if (file.content_type or '').startswith('image/') else 'audio'
        duration = None
        if kind == 'image':
            if len(data) > 5 * 1024 * 1024:
                problem(413, '每张图片不能超过 5 MiB')
            mime, _ = await run_in_threadpool(image_input, data)
        else:
            mime = audio_mime(data)
        item = Attachment(id=str(uuid4()), company_id=actor.company_id, owner_id=actor.id, kind=kind, mime=mime, name=Path(file.filename or 'attachment').name[:180], size=len(data), sha256=checksum(data))
        settings.media_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = settings.media_dir / item.id
        try:
            await run_in_threadpool(path.write_bytes, data)
            path.chmod(0o600)
            if kind == 'audio':
                _, duration = await audio_wav(path, settings)
            item.duration = duration
            db.add(item)
            await db.flush()
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return attachment_dto(item)

    @app.get('/api/v1/uploads/{identifier}/content')
    async def content(identifier: str, actor=AUTH, db=DB):
        item = await owned(db, Attachment, identifier, actor, read=True)
        if actor.id != item.owner_id and not item.message_id:
            problem(404, '附件尚未发送或无权查看')
        path = settings.media_dir / item.id
        if not path.is_file():
            problem(404, '附件文件暂不可用')
        return FileResponse(path, media_type=item.mime, headers={'Content-Disposition': 'inline'})

    @app.post('/api/v1/messages', status_code=202)
    async def send_message(body: SendMessage, idempotency_key: Annotated[str | None, Header()] = None, actor=AUTH, db=DB):
        prior, digest = await idem_begin(db, actor, 'message', idempotency_key, body.model_dump())
        if prior:
            return prior
        attached = [await owned(db, Attachment, aid, actor, lock=True) for aid in body.attachmentIds]
        if any(a.message_id for a in attached) or len({a.kind for a in attached}) > 1 or sum(a.size for a in attached) > 20 * 1024 * 1024 or sum(a.kind == 'audio' for a in attached) > 1:
            problem(422, '附件已使用或组合不受支持，请每次发送最多 4 张图片或一段语音')
        if body.replyTo:
            await owned(db, Message, body.replyTo, actor)
        item = Message(company_id=actor.company_id, owner_id=actor.id, text=body.text, reply_to=body.replyTo)
        db.add(item)
        await db.flush()
        for a in attached:
            a.message_id = item.id
        job = Job(company_id=actor.company_id, owner_id=actor.id, kind='message', target_id=item.id)
        db.add(job)
        await db.flush()
        return idem_save(db, actor, 'message', idempotency_key, digest, {'messageId': item.id, 'jobId': job.id})

    async def list_messages(db, actor, owner_id, cursor, limit):
        query = select(Message).where(Message.company_id == actor.company_id, Message.owner_id == owner_id)
        if cursor:
            anchor = await owned(db, Message, cursor, actor, read=True)
            query = query.where((Message.created_at < anchor.created_at) | ((Message.created_at == anchor.created_at) & (Message.id < anchor.id)))
        rows = list((await db.scalars(query.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit + 1))).all())
        return {'items': [await message_dto(db, m, actor) for m in rows[:limit]], 'nextCursor': rows[limit - 1].id if len(rows) > limit else None}

    @app.get('/api/v1/messages')
    async def messages(cursor: str | None = None, limit: int = Query(50, ge=1, le=100), actor=AUTH, db=DB):
        return await list_messages(db, actor, actor.id, cursor, limit)

    @app.get('/api/v1/messages/{identifier}')
    async def get_message(identifier: str, actor=AUTH, db=DB):
        return await message_dto(db, await owned(db, Message, identifier, actor, read=True), actor)

    @app.patch('/api/v1/messages/{identifier}/transcript')
    async def transcript(identifier: str, body: TranscriptEdit, actor=AUTH, db=DB):
        item = await owned(db, Message, identifier, actor, lock=True)
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
    async def retry(identifier: str, actor=AUTH, db=DB):
        item = await owned(db, Job, identifier, actor, lock=True)
        if item.state not in ('failed', 'awaiting_retry'):
            problem(409, '当前任务不需要重试')
        item.state, item.error, item.request_started = 'queued', '', False
        item.attempt += 1
        item.updated_at = now()
        return job_dto(item)

    @app.get('/api/v1/work-items')
    async def work_items(actor=AUTH, db=DB):
        return {'items': [work_dto(w) for w in (await db.scalars(select(WorkItem).where(WorkItem.owner_id == actor.id).order_by(WorkItem.updated_at.desc()).limit(100))).all()]}

    @app.get('/api/v1/work-items/{identifier}')
    async def work_item(identifier: str, actor=AUTH, db=DB):
        item = await owned(db, WorkItem, identifier, actor, read=True)
        history = (await db.scalars(select(WorkRevision).where(WorkRevision.work_id == item.id).order_by(WorkRevision.revision.desc()).limit(100))).all()
        return {**work_dto(item), 'history': [{'id': r.id, 'revision': r.revision, 'content': r.content, 'sourceIds': r.source_ids, 'createdAt': r.created_at.isoformat()} for r in history]}

    @app.patch('/api/v1/progress-drafts/{identifier}')
    async def edit_draft(identifier: str, body: DraftEdit, actor=AUTH, db=DB):
        draft = await owned(db, ProgressDraft, identifier, actor, lock=True)
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
        query = select(Report).where(Report.owner_id == actor.id, Report.kind == kind)
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
        return {'items': [{'id': r.id, 'workId': r.work_id, 'title': r.content['title'], 'revision': r.revision, 'sourceIds': r.source_ids} for r in sources]}

    @app.post('/api/v1/reports/generate', status_code=202)
    async def generate_report(body: GenerateReport, idempotency_key: Annotated[str | None, Header()] = None, actor=AUTH, db=DB):
        prior, digest = await idem_begin(db, actor, 'generate-report', idempotency_key, body.model_dump(mode='json'))
        if prior:
            return prior
        report, job = await ensure_report(db, actor, body.kind, body.date)
        return idem_save(db, actor, 'generate-report', idempotency_key, digest, {'reportId': report.id, 'jobId': job.id})

    @app.patch('/api/v1/reports/{identifier}')
    async def edit_report(identifier: str, body: ReportEdit, actor=AUTH, db=DB):
        report = await owned(db, Report, identifier, actor, lock=True)
        version(report, body.expectedRevision)
        report.content, report.edited, report.updated_at = body.content.model_dump(), True, now()
        report.revision += 1
        return await report_dto(db, report, actor)

    @app.post('/api/v1/reports/{identifier}/candidate')
    async def adopt_candidate(identifier: str, body: Revision, actor=AUTH, db=DB):
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
            query = select(WorkItem).where(WorkItem.owner_id == member.id)
            if status:
                query = query.where(WorkItem.content['status'].astext == status)
            if start:
                query = query.where(WorkItem.updated_at >= datetime.combine(start, datetime.min.time(), zone))
            if end:
                query = query.where(WorkItem.updated_at < datetime.combine(end, datetime.min.time(), zone) + timedelta(days=1))
            work = (await db.scalars(query.order_by(WorkItem.updated_at.desc()).limit(100))).all()
            last = await db.scalar(select(func.max(Message.created_at)).where(Message.owner_id == member.id))
            report_count = await db.scalar(select(func.count()).select_from(Report).where(Report.owner_id == member.id, Report.published_revision > 0))
            result.append({'member': member_dto(member), 'work': [work_dto(w) for w in work], 'lastMessageAt': last.isoformat() if last else None, 'reportCount': report_count})
        return {'items': result, 'updatedAt': now().isoformat()}

    @app.get('/api/v1/team/members/{identifier}/messages')
    async def team_messages(identifier: str, cursor: str | None = None, limit: int = Query(50, ge=1, le=100), actor=ADMIN, db=DB):
        await visible_member(db, actor, identifier, employee_only=True)
        return await list_messages(db, actor, identifier, cursor, limit)

    @app.get('/api/v1/team/members/{identifier}/work')
    async def team_work(identifier: str, actor=ADMIN, db=DB):
        member = await visible_member(db, actor, identifier, employee_only=True)
        return {'member': member_dto(member), 'items': [work_dto(w) for w in (await db.scalars(select(WorkItem).where(WorkItem.owner_id == identifier).order_by(WorkItem.updated_at.desc()).limit(100))).all()]}

    @app.get('/api/v1/team/members/{identifier}/reports')
    async def team_reports(identifier: str, kind: str = 'daily', cursor: str | None = None, actor=ADMIN, db=DB):
        await visible_member(db, actor, identifier, employee_only=True)
        query = select(Report).where(Report.owner_id == identifier, Report.kind == kind, Report.published_revision > 0)
        if cursor:
            query = query.where(Report.period < cursor)
        rows = (await db.scalars(query.order_by(Report.period.desc()).limit(51))).all()
        return {'items': [await report_dto(db, r, actor) for r in rows[:50]], 'nextCursor': rows[49].period if len(rows) > 50 else None}

    return app


app = create_app()

if __name__ == '__main__':
    import uvicorn
    uvicorn.run('paa_server.api:app', host='127.0.0.1', port=8000)
