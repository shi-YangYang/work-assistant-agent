import hashlib
from fastapi import APIRouter, Query, Request, UploadFile
from fastapi.responses import FileResponse
from paa_server.core.errors import problem
from paa_server.db.base import now
from paa_server.http.dependencies import AUTH, DB, SETTINGS
from paa_server.integrations.media import audio_mime, audio_wav, image_process, preview_path
from paa_server.modules.attachments.documents import attachment_dto, chunk_page, document_type, safe_name, visible_attachment
from paa_server.modules.attachments.models import Attachment
from paa_server.modules.auth.models import Session
from paa_server.modules.members.models import Member
from paa_server.modules.messages.service import active_message
from paa_server.security.locks import company_lock as business_company_lock
from paa_server.security.ownership import owned
from paa_server.tasks.models import Job
from paa_server.tasks.serializers import job_dto
from pathlib import Path
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from uuid import uuid4

router = APIRouter()


@router.post('/api/v1/uploads', status_code=201)
async def upload(file: UploadFile, actor=AUTH, db=DB, settings=SETTINGS):
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
        await business_company_lock(db, initial_company)
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


@router.get('/api/v1/uploads/{identifier}/content')
async def content(identifier: str, actor=AUTH, db=DB, settings=SETTINGS):
    item = await visible_attachment(db, identifier, actor)
    path = settings.media_dir / item.id
    if not path.is_file():
        problem(404, '附件文件暂不可用')
    return FileResponse(path, media_type=item.mime, filename=item.name if item.kind == 'document' else None, content_disposition_type='attachment' if item.kind == 'document' else 'inline', headers={'Content-Security-Policy': "sandbox; default-src 'none'"} if item.kind == 'document' else {'Content-Disposition': 'inline'})


@router.get('/api/v1/uploads/{identifier}/preview')
async def media_preview(identifier: str, request: Request, actor=AUTH, db=DB, settings=SETTINGS):
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
    await business_company_lock(db, initial_company)
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


@router.get('/api/v1/uploads/{identifier}/extraction')
async def extraction(identifier: str, start: int = Query(0, ge=0, le=2000), limit: int = Query(3, ge=1, le=3), revision: int | None = None, actor=AUTH, db=DB):
    item = await visible_attachment(db, identifier, actor)
    if item.kind != 'document':
        problem(422, '该附件没有文档提取内容')
    if revision is not None and revision != item.extraction_revision:
        problem(409, '文件提取版本已变化，请重新打开来源')
    return await chunk_page(db, item, start, limit)


@router.post('/api/v1/uploads/{identifier}/retry', status_code=202)
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
