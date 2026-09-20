"""Private company enrollment queue, bounded extraction and authorized snapshots."""
import asyncio
from datetime import timedelta
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from fastapi import Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from paa_voiceprints import MODEL_ID, DIMENSION
from .business_access import company_lock
from .documents import safe_name
from .media import audio_mime, audio_wav
from .models import Member, Voiceprint, now
from .service import problem

MAX_BYTES = 20 * 1024 * 1024
log = logging.getLogger(__name__)


def valid_templates(value):
    return isinstance(value, list) and 1 <= len(value) <= 12 and all(
        isinstance(row, list) and len(row) == DIMENSION and
        all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in row) and
        .98 <= math.sqrt(sum(n * n for n in row)) <= 1.02 for row in value)


def private_path(settings, identifier):
    # File names originate solely from our random IDs, never client input.
    return settings.media_dir / 'voiceprints' / identifier


def dto(item, member):
    incompatible = bool(item and item.templates and (item.model_id != MODEL_ID or not valid_templates(item.templates)))
    return {'memberId': member.id, 'name': member.name, 'role': member.role,
            'active': member.active, 'state': 'incompatible' if incompatible and item.state not in ('queued', 'processing') else item.state if item else 'empty', 'revision': item.revision if item else 0,
            'ready': bool(item and item.templates and not incompatible), 'filename': item.filename if item else '',
            'error': '声纹版本不兼容，请重新上传登记录音' if incompatible else item.error if item else '', 'speechSeconds': item.speech_seconds if item else 0,
            'updatedAt': item.updated_at.isoformat() if item else None}


def register_routes(app, ADMIN, DESKTOP, DB, settings):
    async def member(db, actor, identifier):
        found = await db.scalar(select(Member).where(Member.id == identifier, Member.company_id == actor.company_id, Member.deleted.is_(False)))
        if not found:
            problem(404, '成员不存在或已停用')
        return found

    async def enrollment(db, actor, identifier):
        target = await member(db, actor, identifier)
        item = await db.scalar(select(Voiceprint).where(Voiceprint.company_id == actor.company_id, Voiceprint.member_id == target.id))
        return target, item

    @app.get('/api/v1/settings/voiceprints')
    async def listing(actor=ADMIN, db=DB):
        members = (await db.scalars(select(Member).where(Member.company_id == actor.company_id, Member.deleted.is_(False)).order_by(Member.name).limit(501))).all()
        stored = {v.member_id: v for v in (await db.scalars(select(Voiceprint).where(Voiceprint.company_id == actor.company_id))).all()}
        return {'modelId': MODEL_ID, 'items': [dto(stored.get(m.id), m) for m in members], 'limit': 500}

    @app.post('/api/v1/settings/voiceprints/{identifier}', status_code=202)
    async def upload(identifier: str, file: UploadFile, consent: bool = Form(...), expectedRevision: int = Form(..., ge=0), actor=ADMIN, db=DB):
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

    @app.post('/api/v1/settings/voiceprints/{identifier}/retry', status_code=202)
    async def retry(identifier: str, actor=ADMIN, db=DB):
        target, item = await enrollment(db, actor, identifier)
        if not item or item.state != 'failed' or not item.pending_path:
            problem(409, '当前没有可重试的登记任务')
        item.revision += 1
        item.state, item.error, item.lease_until, item.updated_at = 'queued', '', None, now()
        return dto(item, target)

    @app.get('/api/v1/settings/voiceprints/{identifier}/audio')
    async def original(identifier: str, actor=ADMIN, db=DB):
        _, item = await enrollment(db, actor, identifier)
        path = private_path(settings, item.pending_path or item.ready_path) if item else None
        if not path or not path.is_file():
            problem(404, '登记原录音不存在')
        return FileResponse(path, media_type='application/octet-stream', filename=item.filename)

    @app.delete('/api/v1/settings/voiceprints/{identifier}')
    async def remove(identifier: str, actor=ADMIN, db=DB):
        _, item = await enrollment(db, actor, identifier)
        if item:
            paths = [p for p in (item.ready_path, item.pending_path) if p]
            await db.delete(item)
            await db.commit()
            for path in paths:
                private_path(settings, path).unlink(missing_ok=True)
        return {'ok': True}

    @app.get('/api/v1/desktop/voiceprints')
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


async def extract(path, settings):
    """Only this subprocess imports the optional CPU model runtime."""
    wav, _ = await audio_wav(path, settings)
    with tempfile.TemporaryDirectory(prefix='paa-voiceprint-') as directory:
        audio = Path(directory) / 'sample.wav'
        audio.write_bytes(wav)
        env = {**os.environ, 'OMP_NUM_THREADS': '2', 'MKL_NUM_THREADS': '2', 'OPENBLAS_NUM_THREADS': '2'}
        try:
            process = await asyncio.create_subprocess_exec(str(settings.voiceprint_python), '-m', 'paa_voiceprints', str(audio), '--model', str(settings.voiceprint_model), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=env)
        except OSError:
            raise ValueError('声纹运行环境未安装，请联系管理员安装公司声纹组件') from None
        async def bounded():
            data = await process.stdout.read(256 * 1024 + 1)
            if len(data) > 256 * 1024:
                raise ValueError('声纹处理结果异常，请重新上传清晰的单人录音')
            await process.wait()
            try:
                result = json.loads(data)
            except (ValueError, UnicodeError):
                raise ValueError('声纹组件未就绪，请联系管理员检查运行环境和模型') from None
            errors = {'audio_quality': '有效语音不足，请上传至少 6 秒清晰的单人讲话', 'audio_duration': '录音不能超过 3 分钟', 'audio_format': '录音格式无法读取，请换用 WAV 或 MP3', 'model_unavailable': '声纹模型未就绪，请联系管理员检查模型文件', 'inference_failed': '声纹提取失败，请尝试更清晰的单人录音'}
            if process.returncode or 'error' in result:
                raise ValueError(errors.get(result.get('error', {}).get('code'), '声纹提取失败，请联系管理员检查运行环境'))
            if result.get('modelId') != MODEL_ID or not valid_templates(result.get('templates')):
                raise ValueError('声纹模型版本或结果不兼容，请检查组件版本')
            return result
        try:
            return await asyncio.wait_for(bounded(), timeout=180)
        except asyncio.TimeoutError:
            raise ValueError('声纹提取超时，请使用较短录音后重试') from None
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()


async def process_once(sessions, settings, *, extractor=extract):
    async with sessions.begin() as db:
        item = await db.scalar(select(Voiceprint).where((Voiceprint.state == 'queued') | ((Voiceprint.state == 'processing') & (Voiceprint.lease_until < now()))).order_by(Voiceprint.created_at).with_for_update(skip_locked=True).limit(1))
        if item is None:
            return False
        item.state, item.lease_until = 'processing', now() + timedelta(minutes=5)
        identifier, company_id, revision, pending = item.id, item.company_id, item.revision, item.pending_path
    error, result = '', None
    try:
        result = await extractor(private_path(settings, pending), settings)
    except asyncio.CancelledError:
        async with sessions.begin() as db:
            item = await db.get(Voiceprint, identifier)
            if item and item.revision == revision:
                item.state, item.lease_until = 'queued', None
        raise
    except HTTPException as exc:
        error = exc.detail.get('message', '录音无法读取，请重新上传') if isinstance(exc.detail, dict) else '录音无法读取，请重新上传'
    except ValueError as exc:
        error = str(exc)[:220]
    except Exception as exc:
        log.warning('voiceprint extraction failure_type=%s', type(exc).__name__)
        error = '声纹提取失败，请检查声纹组件后重试'
    old_ready = ''
    async with sessions.begin() as db:
        await company_lock(db, company_id)
        item = await db.scalar(select(Voiceprint).where(Voiceprint.id == identifier).with_for_update())
        if not item or item.revision != revision or item.pending_path != pending:
            return True
        item.lease_until, item.updated_at = None, now()
        if error:
            item.state, item.error = 'failed', error
        else:
            old_ready = item.ready_path
            item.state, item.error, item.model_id = 'ready', '', MODEL_ID
            item.templates = result['templates']
            item.speech_seconds = round(result['speechSeconds'])
            item.ready_path, item.pending_path = pending, ''
    if old_ready and old_ready != pending:
        private_path(settings, old_ready).unlink(missing_ok=True)
    return True


async def worker_loop(sessions, settings, stop):
    while not stop.is_set():
        try:
            if await process_once(sessions, settings):
                continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning('voiceprint worker failure_type=%s', type(exc).__name__)
        try:
            await asyncio.wait_for(stop.wait(), timeout=2)
        except asyncio.TimeoutError:
            pass
