import asyncio
from datetime import timedelta
import json
import logging
import signal

import httpx
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import delete, exists, select, update
from sqlalchemy.orm import aliased
from fastapi import HTTPException

from . import business_access as business
from .feedback import publish, update_feedback
from .usage import RequestRecord, interrupt_usage
from .agent.harness import BudgetExceeded, LostLease, RunContext, attachment_inventory, invoke_harness, lease, reserve_call
from .config import Settings
from .db import database
from .documents import prepare_document, verified_citations
from .media import audio_wav, data_url, image_process, remove_media, MAX_MESSAGE_IMAGE_BLOCKS, MAX_MESSAGE_IMAGE_PIXELS, MAX_MESSAGE_IMAGE_BYTES
from .models import BusinessAction, Attachment, Job, LoginAttempt, Member, Message, ModelUsage, ProgressDraft, Session, now
from .service import owned
from .report_schedule import schedule_once

log = logging.getLogger('paa.company')


async def interrupted_state(db, job):
    if job.result.get('reportSaved'):
        return 'queued'
    rows = (await db.scalars(select(ModelUsage).where(ModelUsage.job_id == job.id, ModelUsage.job_attempt == job.attempt, ModelUsage.job_fence == job.fence))).all()
    # A reservation is not a sent request. Old jobs without request records use
    # their conservative legacy marker; never silently repeat an unknown call.
    sent = any(row.started_at is not None for row in rows) if rows else job.request_started
    return 'awaiting_retry' if sent else 'queued'


async def claim(sessions, owner_id=None, *, company_id=None):
    scope = [*([Job.owner_id == owner_id] if owner_id else []), *([Job.company_id == company_id] if company_id else [])]
    async with sessions() as db:
        expired = (await db.execute(select(Job.id, Job.company_id, Job.owner_id).where(Job.state == 'running', Job.lease_until < now(), *scope).order_by(Job.created_at, Job.id).limit(50))).all()
    for identifier, company, owner in expired:
        async with sessions.begin() as db:
            await business.company_lock(db, company)
            actor = await db.scalar(select(Member).where(Member.id == owner).with_for_update())
            job = await db.scalar(select(Job).where(Job.id == identifier).with_for_update())
            if job.state != 'running' or job.lease_until is None or job.lease_until >= now():
                continue
            await interrupt_usage(db, job)
            update_feedback(job)
            job.state = await interrupted_state(db, job)
            if job.state == 'queued':
                job.request_started = False
            if not actor.active or (job.kind == 'report' and actor.role != 'employee'):
                job.state = 'cancelled'
            job.error = '处理意外中断，请确认后重试' if job.state == 'awaiting_retry' else ''
            job.lease_until, job.fence, job.updated_at = None, job.fence + 1, now()
    async with sessions.begin() as db:
        running = aliased(Job)
        query = select(Job).join(Member, Member.id == Job.owner_id).where(Job.state == 'queued', Member.active.is_(True), ((Job.kind != 'report') | (Member.role == 'employee')), ~exists(select(running.id).where(running.owner_id == Job.owner_id, running.state == 'running')), *scope).order_by(Job.created_at, Job.id)
        company = await db.scalar(query.with_only_columns(Job.company_id).limit(1))
        if not company:
            return None
        # Same order as all API/harness writes, including expired-lease recovery.
        await business.company_lock(db, company)
        job = await db.scalar(query.where(Job.company_id == company).with_for_update(of=(Job, Member), skip_locked=True).limit(1))
        if not job:
            return None
        if not job.access:
            job.access = business.scope(await db.get(Member, job.owner_id))
        job.state, job.fence, job.lease_until, job.updated_at = 'running', job.fence + 1, now() + timedelta(seconds=90), now()
        update_feedback(job, 'preparing', '')
        return job


async def heartbeat(context):
    while True:
        await asyncio.sleep(15)
        async with context.sessions.begin() as db:
            job, _ = await lease(db, context)
            job.lease_until = now() + timedelta(seconds=90)


async def asr(context, attachment):
    from .model_services import resolve_bound
    from .model_provider import transcribe, safe_error
    settings = context.settings
    wav, _ = await audio_wav(settings.media_dir / attachment.id, settings)
    usage_id = await reserve_call(context, 'asr')
    record = RequestRecord(context.sessions, usage_id)
    try:
        async with context.sessions() as db:
            await lease(db, context)
            config, key = await resolve_bound(db, settings, context.company_id, context.model_binding or {}, 'asr')
        transcript, usage = await record.run(lambda event: asyncio.wait_for(transcribe(settings, config, key, wav, on_event=event), 60))
    except Exception as error:
        await record.finish(error)
        raise safe_error(error) from None
    return transcript


async def process_job(job, sessions, settings, checkpointer, *, model=None, asr_provider=None, reply_model=None):
    try:
        await asyncio.wait_for(_process_job(job, sessions, settings, checkpointer, model=model, asr_provider=asr_provider, reply_model=reply_model), timeout=450)
    except asyncio.TimeoutError:
        async with sessions.begin() as db:
            current = await db.scalar(select(Job).where(Job.id == job.id).with_for_update())
            if current.state == 'running' and current.fence == job.fence:
                await interrupt_usage(db, current)
                update_feedback(current)
                current.state = 'awaiting_retry' if current.request_started else 'failed'
                current.error = '处理超时，原始内容已保存；服务可能已计费，请确认后重试'
                current.lease_until, current.updated_at = None, now()


async def _process_job(job, sessions, settings, checkpointer, *, model=None, asr_provider=None, reply_model=None):
    context = RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, settings)
    heartbeat_task = asyncio.create_task(heartbeat(context))
    try:
        if job.kind == 'report':
            from .report_generation import generate
            await generate(context, model)
            return
        if job.kind == 'document':
            await prepare_document(context, job.target_id)
            async with sessions.begin() as db:
                live, _ = await lease(db, context)
                live.state, live.phase, live.error, live.lease_until = 'succeeded', 'complete', '', None
                live.updated_at = now()
            return
        async with sessions() as db:
            _, actor = await lease(db, context)
            message = await owned(db, Message, job.target_id, actor)
            attachments = (await db.scalars(select(Attachment).where(Attachment.message_id == message.id, Attachment.deleted.is_(False)))).all()
            order = job.result.get('attachmentOrder', [])
            attachments = sorted(attachments, key=lambda a: order.index(a.id) if a.id in order else a.created_at.timestamp())
            transcript_revision = message.transcript_revision
            text, transcript = message.text, message.transcript
            reply_to = message.reply_to
        documents = []
        for attachment in attachments:
            if attachment.kind == 'document':
                documents.append(await prepare_document(context, attachment.id))
        # Parsing is independent of credentials and survives model configuration errors.
        from .model_services import bind_job
        context.model_purpose = 'assistant'
        async with sessions.begin() as binding_db:
            live, _ = await lease(binding_db, context)
            context.model_binding = await bind_job(binding_db, live, settings)
            context.config_attempt = live.config_attempt
        # A resumed graph may already have read tools in its checkpoint. Restore
        # only server-recorded, still-authorized evidence; changed file revisions
        # also enter the input digest so stale tool outputs cannot be resumed.
        from .documents import agent_attachment, document_statement
        import hashlib
        async with sessions() as db:
            live, actor = await lease(db, context)
            statement = await document_statement(db, actor, live)
            versions = (await db.execute(statement.with_only_columns(Attachment.id, Attachment.extraction_revision, Attachment.extraction_status).order_by(Attachment.id))).all()
            context.document_snapshot = hashlib.sha256(json.dumps([list(row) for row in versions]).encode()).hexdigest() if versions else ''
            for token, evidence in live.result.get('documentReads', {}).items():
                aid, revision, ordinal = evidence
                try:
                    document = await agent_attachment(db, aid, actor, live)
                except HTTPException:
                    continue
                context.document_versions[aid] = document.extraction_revision
                if document.extraction_revision == revision:
                    context.document_reads[token] = tuple(evidence)
        import time
        context.started = time.monotonic()
        context.document_versions.update({item['id']: item['extraction']['revision'] for item in documents})
        blocks = []
        image_manifest = []
        image_pixels = image_bytes = 0
        for attachment in attachments:
            if attachment.kind == 'audio' and not transcript:
                await publish(context, 'transcribing', force=True)
                transcript = await (asr_provider(context, attachment) if asr_provider else asr(context, attachment))
                if not transcript or not transcript.strip():
                    raise ValueError('语音未识别出文字，请检查录音后重试或修正语音文字；其他材料已保留')
                async with sessions.begin() as db:
                    await lease(db, context)
                    message = await db.scalar(select(Message).where(Message.id == job.target_id).with_for_update())
                    if message.transcript_revision == transcript_revision:
                        message.transcript, message.transcript_revision = transcript, transcript_revision + 1
                    else:
                        transcript = message.transcript
                    # The selected text and revision must describe the same committed
                    # source, including a correction made while ASR was in flight.
                    transcript_revision = message.transcript_revision
            elif attachment.kind == 'image':
                result = await image_process(settings.media_dir / attachment.id, 'model')
                image_pixels += result['pixels']
                image_bytes += result['bytes']
                if len(blocks) + len(result['tiles']) > MAX_MESSAGE_IMAGE_BLOCKS or image_pixels > MAX_MESSAGE_IMAGE_PIXELS or image_bytes > MAX_MESSAGE_IMAGE_BYTES:
                    raise ValueError('本次图片超出处理预算，请减少图片或裁剪后重新发送；原始材料已保存')
                for tile in result['tiles']:
                    blocks.append({'type': 'image_url', 'image_url': {'url': f"data:{tile['mime']};base64,{tile['data']}"}})
                image_manifest.append({'attachmentId': attachment.id, 'name': attachment.name, 'size': [result['width'], result['height']], 'regions': [tile['box'] for tile in result['tiles']], 'complete': result['complete'], 'warnings': result['warnings']})
        if job.kind == 'message':
            context.source_revision = transcript_revision
        blocks.insert(0, {'type': 'text', 'text': f'原消息 ID：{job.target_id}\n' + (f'补充此前消息：{reply_to}\n' if reply_to else '') + text})
        if attachments:
            blocks[0]['text'] += '\n本次完整附件清单（已上传的原始材料；不代表所有内容均已读取）：' + json.dumps(attachment_inventory(attachments, transcript, transcript_revision), ensure_ascii=False)
        if transcript:
            audio_names = [attachment.name for attachment in attachments if attachment.kind == 'audio']
            blocks[0]['text'] += '\n语音内容来源：' + json.dumps({'receivedAudioFiles': audio_names, 'status': '已收到音频，以下为该音频的当前转写；如有用户纠正，以纠正版本为准', 'transcript': transcript}, ensure_ascii=False)
        if image_manifest:
            blocks[0]['text'] += '\n图片按附件及区域顺序排列，坐标为方向校正后的原图像素；必须如实说明未读取范围：' + json.dumps(image_manifest, ensure_ascii=False)
        if documents:
            blocks[0]['text'] += '\n本次文档目录（仅含文档，不含图片和语音；正文需通过工具读取，状态/覆盖范围必须如实说明）：' + json.dumps(documents, ensure_ascii=False, sort_keys=True)
        if not model and not context.model_binding.get(context.model_purpose):
            raise ValueError('当前用途的模型尚未配置，请联系管理员；原始内容已保存')
        await publish(context, 'generating', force=True)
        answer = await invoke_harness(context, checkpointer, blocks, model)
        from .agent.reply_review import review_reply
        review = await review_reply(context, answer, model=reply_model or model)
        async with sessions.begin() as db:
            live, actor = await lease(db, context)
            message = await owned(db, Message, job.target_id, actor, lock=True)
            from .business_actions import message_actions, receipt_reply
            answer = receipt_reply(review, await message_actions(db, actor, message))
            message.reply, message.citations = await verified_citations(db, context, answer)
            message.access = live.access
            drafts = (await db.scalars(select(ProgressDraft).where(ProgressDraft.message_id == message.id, ProgressDraft.status == 'pending'))).all()
            for draft in drafts:
                business.inherit(actor, draft, live)
                await business.require(db, actor, draft.access)
            if live.access.get('team'):
                message.reply, references = await business.citations(db, actor, live.access, message.reply)
                message.citations = [*message.citations, *references]
                message.reply += await business.query_summary(db, live.result.get('businessQueries', []))
            source_ids = set(context.document_versions) | {row['id'] for row in documents}
            if source_ids:
                source_documents = (await db.scalars(select(Attachment).where(Attachment.id.in_(source_ids), Attachment.deleted.is_(False), Attachment.owner_id == actor.id))).all()
                coverage = []
                for document in source_documents:
                    read = len({entry[2] for entry in context.document_reads.values() if entry[0] == document.id and entry[1] == document.extraction_revision})
                    if document.extraction_status == 'failed':
                        detail = '未能使用：' + document.extraction_info.get('error', '解析失败')
                    else:
                        detail = f"实际读取 {read}/{document.extraction_info.get('chunks', 0)} 个文字分段"
                        if document.extraction_status == 'partial':
                            detail += '；文件仅部分可读'
                    coverage.append(document.name + '：' + detail)
                message.reply += '\n\n材料范围：\n' + '\n'.join(coverage)
            image_warnings = [entry['name'] + '：' + '；'.join(entry['warnings']) for entry in image_manifest if entry['warnings']]
            if image_warnings:
                message.reply += '\n\n图片范围：\n' + '\n'.join(image_warnings)
            has_actions = await db.scalar(select(BusinessAction.id).where(BusinessAction.message_id == message.id, BusinessAction.state.in_(['succeeded', 'pending', 'running'])).limit(1))
            live.state = 'succeeded' if message.suggestions or has_actions else 'awaiting_input'
            update_feedback(live, 'complete', '')
            live.phase, live.error, live.lease_until, live.updated_at = 'complete', '', None, now()
    except LostLease:
        log.info('job=%s lost lease', job.id)
    except Exception as error:
        if isinstance(error, (ValueError, BudgetExceeded)):
            reason = str(error)[:300]
        elif isinstance(error, HTTPException):
            reason = error.detail.get('message', '媒体处理失败') if isinstance(error.detail, dict) else '媒体处理失败'
        elif isinstance(error, (httpx.HTTPError, asyncio.TimeoutError)):
            reason = '模型服务未完成响应，请稍后重试；可能产生重复计费'
        else:
            reason = '本次处理未完成，请重试或联系管理员'
        log.warning('job=%s failure_type=%s', job.id, type(error).__name__)
        async with sessions.begin() as db:
            live = await db.scalar(select(Job).where(Job.id == job.id).with_for_update())
            if live.fence == context.fence and live.state == 'running':
                await interrupt_usage(db, live)
                update_feedback(live)
                revoked = (isinstance(error, HTTPException) and isinstance(error.detail, dict) and error.detail.get('code') == 'business_access_changed') or (isinstance(error, ValueError) and str(error).startswith('账号权限已变化'))
                live.state = 'cancelled' if revoked else 'awaiting_retry' if live.request_started else 'failed'
                live.error, live.lease_until, live.updated_at = reason, None, now()
    finally:
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)


async def maintenance(sessions, settings):
    from .deletion import clean_files
    async with sessions.begin() as db:
        await clean_files(db, settings)
        old = (await db.scalars(select(Attachment).where(Attachment.message_id.is_(None), Attachment.created_at < now() - timedelta(hours=24)).with_for_update(skip_locked=True))).all()
        for attachment in old:
            remove_media(settings, attachment.id)
            await db.delete(attachment)
        await db.execute(update(Job).where(Job.state.in_(('succeeded', 'awaiting_input', 'failed', 'awaiting_retry', 'cancelled')), Job.updated_at < now() - timedelta(days=1), Job.feedback != {}).values(feedback={}))
        await db.execute(delete(Session).where(Session.expires_at < now()))
        await db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < now() - timedelta(minutes=10)))


async def scheduler(sessions, settings):
    while True:
        try:
            await schedule_once(sessions)
            await maintenance(sessions, settings)
        except Exception as error:
            log.warning('scheduler failure_type=%s', type(error).__name__)
        await asyncio.sleep(60)


async def worker_slot(sessions, settings, stop, *, saver_factory=None, runner=process_job):
    factory = saver_factory or (lambda: AsyncPostgresSaver.from_conn_string(settings.checkpoint_url))
    async with factory() as saver:
        while not stop.is_set():
            job = None
            try:
                job = await claim(sessions)
                if job:
                    await runner(job, sessions, settings, saver)
                else:
                    try:
                        await asyncio.wait_for(stop.wait(), 1)
                    except asyncio.TimeoutError:
                        pass
            except asyncio.CancelledError:
                if job:
                    async with sessions.begin() as db:
                        await business.company_lock(db, job.company_id)
                        await db.scalar(select(Member).where(Member.id == job.owner_id).with_for_update())
                        live = await db.scalar(select(Job).where(Job.id == job.id).with_for_update())
                        if live.state == 'running' and live.fence == job.fence:
                            await interrupt_usage(db, live)
                            live.state = await interrupted_state(db, live)
                            if live.state == 'queued':
                                live.request_started = False
                            live.error = '处理已中断，请确认后重试' if live.state == 'awaiting_retry' else ''
                            live.fence, live.lease_until, live.updated_at = live.fence + 1, None, now()
                            update_feedback(live)
                raise
            except Exception as error:
                log.warning('worker slot failure_type=%s', type(error).__name__)
                try:
                    await asyncio.wait_for(stop.wait(), 1)
                except asyncio.TimeoutError:
                    pass


async def run_slots(sessions, settings, stop, *, saver_factory=None, runner=process_job, shutdown_timeout=10):
    tasks = [asyncio.create_task(worker_slot(sessions, settings, stop, saver_factory=saver_factory, runner=runner)) for _ in range(settings.worker_concurrency)]
    try:
        stop_task = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait([stop_task, *tasks], return_when=asyncio.FIRST_COMPLETED)
        if stop_task not in done:
            stop_task.cancel()
            await asyncio.gather(stop_task, return_exceptions=True)
            for task in done:
                task.result()
            raise RuntimeError('Worker processing slot exited unexpectedly')
        await asyncio.wait(tasks, timeout=shutdown_timeout)
    finally:
        if 'stop_task' in locals() and not stop_task.done():
            stop_task.cancel()
            await asyncio.gather(stop_task, return_exceptions=True)
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def main():
    settings = Settings()
    engine, sessions = database(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signum, stop.set)
        except NotImplementedError:
            pass
    # This deployment deliberately runs one bounded worker. A second process
    # exits instead of silently multiplying model requests and connections.
    from psycopg import AsyncConnection
    async with await AsyncConnection.connect(settings.checkpoint_url, autocommit=True) as guard:
        row = await (await guard.execute('SELECT pg_try_advisory_lock(17017)')).fetchone()
        if not row[0]:
            await engine.dispose()
            raise RuntimeError('A company worker is already running')
        timer = asyncio.create_task(scheduler(sessions, settings))
        try:
            await run_slots(sessions, settings, stop)
        finally:
            timer.cancel()
            await asyncio.gather(timer, return_exceptions=True)
            await engine.dispose()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
