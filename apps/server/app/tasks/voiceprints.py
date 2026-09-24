import asyncio
import json
import os
import tempfile
from datetime import timedelta
from fastapi import HTTPException
from app.db.base import now
from app.integrations.media import audio_wav
from app.modules.voiceprints.models import Voiceprint
from app.modules.voiceprints.service import log, private_path, valid_templates
from app.security.locks import company_lock
from paa_voiceprints import MODEL_ID
from pathlib import Path
from sqlalchemy import select


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
