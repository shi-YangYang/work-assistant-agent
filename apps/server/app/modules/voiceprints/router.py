import hashlib
import json
from fastapi import APIRouter, Form, UploadFile
from fastapi.responses import FileResponse
from app.core.errors import problem
from app.db.base import now
from app.http.dependencies import ADMIN, DB, SETTINGS
from app.http.desktop_dependencies import DESKTOP
from app.integrations.media import audio_mime
from app.modules.attachments.documents import safe_name
from app.modules.members.models import Member
from app.modules.voiceprints.models import Voiceprint
from app.modules.voiceprints.service import MAX_BYTES, dto, enrollment, private_path, valid_templates
from paa_voiceprints import MODEL_ID
from sqlalchemy import func, select
from uuid import uuid4

router = APIRouter()


@router.get('/api/v1/settings/voiceprints')
async def listing(actor=ADMIN, db=DB):
    members = (await db.scalars(select(Member).where(Member.company_id == actor.company_id, Member.deleted.is_(False)).order_by(Member.name).limit(501))).all()
    stored = {v.member_id: v for v in (await db.scalars(select(Voiceprint).where(Voiceprint.company_id == actor.company_id))).all()}
    return {'modelId': MODEL_ID, 'items': [dto(stored.get(m.id), m) for m in members], 'limit': 500}


@router.post('/api/v1/settings/voiceprints/{identifier}', status_code=202)
async def upload(identifier: str, file: UploadFile, consent: bool = Form(...), expectedRevision: int = Form(..., ge=0), actor=ADMIN, db=DB, settings=SETTINGS):
    if not consent:
        problem(422, '请先确认本人知情并同意登记声纹')
    target, item = await enrollment(db, actor, identifier)
    if not target.active:
        problem(409, '成员已停用，不能登记新的声纹')
    if (item.revision if item else 0) != expectedRevision:
        problem(409, '声纹记录已变化，请刷新后重试')
    if item and item.state in ('queued', 'processing'):
        problem(409, '此成员正在处理，请等待完成后再替换')
    count = await db.scalar(select(func.count()).select_from(Voiceprint).where(Voiceprint.company_id == actor.company_id))
    if item is None and count >= 500:
        problem(422, '每家公司最多登记 500 位成员声纹')
    data = await file.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        problem(413, '请选择不超过 20 MiB 的录音')
    audio_mime(data)
    filename = safe_name(file.filename)[:160]
    root = settings.media_dir / 'voiceprints'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = private_path(settings, str(uuid4()))
    path.write_bytes(data)
    path.chmod(0o600)
    old_pending = item.pending_path if item else ''
    try:
        if item is None:
            item = Voiceprint(company_id=actor.company_id, member_id=target.id, consent_by=actor.id)
            db.add(item)
            await db.flush()
        else:
            item.revision += 1
        item.pending_path, item.filename = path.name, filename
        item.state, item.error, item.lease_until = 'queued', '', None
        item.consent_by, item.consent_at, item.updated_at = actor.id, now(), now()
        await db.commit()
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    if old_pending:
        private_path(settings, old_pending).unlink(missing_ok=True)
    return dto(item, target)


@router.post('/api/v1/settings/voiceprints/{identifier}/retry', status_code=202)
async def retry(identifier: str, actor=ADMIN, db=DB):
    target, item = await enrollment(db, actor, identifier)
    if not item or item.state != 'failed' or not item.pending_path:
        problem(409, '当前没有可重试的登记任务')
    item.revision += 1
    item.state, item.error, item.lease_until, item.updated_at = 'queued', '', None, now()
    return dto(item, target)


@router.get('/api/v1/settings/voiceprints/{identifier}/audio')
async def original(identifier: str, actor=ADMIN, db=DB, settings=SETTINGS):
    _, item = await enrollment(db, actor, identifier)
    path = private_path(settings, item.pending_path or item.ready_path) if item else None
    if not path or not path.is_file():
        problem(404, '登记原录音不存在')
    return FileResponse(path, media_type='application/octet-stream', filename=item.filename)


@router.delete('/api/v1/settings/voiceprints/{identifier}')
async def remove(identifier: str, actor=ADMIN, db=DB, settings=SETTINGS):
    _, item = await enrollment(db, actor, identifier)
    if item:
        paths = [p for p in (item.ready_path, item.pending_path) if p]
        await db.delete(item)
        await db.commit()
        for path in paths:
            private_path(settings, path).unlink(missing_ok=True)
    return {'ok': True}


@router.get('/api/v1/desktop/voiceprints')
async def snapshot(actor=DESKTOP, db=DB):
    if actor.role != 'admin':
        problem(403, '仅管理员可以同步公司声纹')
    rows = (await db.execute(select(Voiceprint, Member).join(Member, Voiceprint.member_id == Member.id).where(Voiceprint.company_id == actor.company_id, Member.active.is_(True)).order_by(Member.id).limit(501))).all()
    if len(rows) > 500:
        problem(422, '公司声纹数量超过当前支持范围')
    if any(v.templates and (v.model_id != MODEL_ID or not valid_templates(v.templates)) for v, _ in rows):
        problem(409, '公司声纹版本不兼容，请管理员重新登记后再同步', 'voiceprint_model_mismatch')
    profiles = [{'memberId': m.id, 'name': m.name, 'templates': v.templates} for v, m in rows if v.model_id == MODEL_ID and valid_templates(v.templates)]
    revision = hashlib.sha256(json.dumps(profiles, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'modelId': MODEL_ID, 'revision': revision, 'profiles': profiles}
