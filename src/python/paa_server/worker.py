import asyncio
from datetime import datetime, time, timedelta
import json
import logging
from zoneinfo import ZoneInfo

import httpx
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import delete, exists, select
from sqlalchemy.orm import aliased
from fastapi import HTTPException

from .agent.harness import BudgetExceeded, LostLease, RunContext, invoke_harness, lease, reserve_call
from .config import Settings
from .db import database
from .media import audio_wav, data_url, image_input
from .models import Attachment, Company, Job, LoginAttempt, Member, Message, Report, Session, WorkRevision, now
from .service import ensure_report, owned

log = logging.getLogger('paa.company')


async def claim(sessions, owner_id=None):
    async with sessions.begin() as db:
        expired = (await db.scalars(select(Job).where(Job.state == 'running', Job.lease_until < now(), *([Job.owner_id == owner_id] if owner_id else [])).with_for_update(skip_locked=True))).all()
        for job in expired:
            job.state = 'awaiting_retry' if job.request_started else 'queued'
            job.error = '处理意外中断，服务可能已计费；请确认后重试' if job.request_started else ''
            job.lease_until, job.fence, job.updated_at = None, job.fence + 1, now()
        await db.flush()
        running = aliased(Job)
        job = await db.scalar(select(Job).join(Member, Member.id == Job.owner_id).where(Job.state == 'queued', Member.active.is_(True), ~exists(select(running.id).where(running.owner_id == Job.owner_id, running.state == 'running')), *([Job.owner_id == owner_id] if owner_id else [])).order_by(Job.created_at).with_for_update(of=(Job, Member), skip_locked=True).limit(1))
        if not job:
            return None
        job.state, job.fence, job.lease_until, job.updated_at = 'running', job.fence + 1, now() + timedelta(seconds=90), now()
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
    async with context.sessions() as db:
        await lease(db, context)
        config, key = await resolve_bound(db, settings, context.company_id, context.model_binding or {}, 'asr')
    try:
        transcript, usage = await asyncio.wait_for(transcribe(settings, config, key, wav), 60)
    except Exception as error:
        raise safe_error(error) from None
    if usage:
        from .models import ModelUsage
        async with context.sessions.begin() as db:
            await lease(db, context)
            row = await db.get(ModelUsage, usage_id)
            row.input_tokens, row.output_tokens = usage.get('prompt_tokens', 0), usage.get('completion_tokens', 0)
    return transcript


async def process_job(job, sessions, settings, checkpointer, *, model=None, asr_provider=None):
    try:
        await asyncio.wait_for(_process_job(job, sessions, settings, checkpointer, model=model, asr_provider=asr_provider), timeout=180)
    except asyncio.TimeoutError:
        async with sessions.begin() as db:
            current = await db.scalar(select(Job).where(Job.id == job.id).with_for_update())
            if current.state == 'running' and current.fence == job.fence:
                current.state = 'awaiting_retry' if current.request_started else 'failed'
                current.error = '处理超时，原始内容已保存；服务可能已计费，请确认后重试'
                current.lease_until, current.updated_at = None, now()


async def _process_job(job, sessions, settings, checkpointer, *, model=None, asr_provider=None):
    context = RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, settings)
    heartbeat_task = asyncio.create_task(heartbeat(context))
    try:
        from .model_services import bind_job
        context.model_purpose = 'report' if job.kind == 'report' else 'assistant'
        async with sessions.begin() as binding_db:
            live, _ = await lease(binding_db, context)
            context.model_binding = await bind_job(binding_db, live, settings)
            context.config_attempt = live.config_attempt
        async with sessions() as db:
            _, actor = await lease(db, context)
            if job.kind == 'message':
                message = await owned(db, Message, job.target_id, actor)
                attachments = (await db.scalars(select(Attachment).where(Attachment.message_id == message.id))).all()
                transcript_revision = message.transcript_revision
                text, transcript = message.text, message.transcript
                reply_to = message.reply_to
            else:
                report = await owned(db, Report, job.target_id, actor)
                sources = (await db.scalars(select(WorkRevision).where(WorkRevision.id.in_(job.result.get('sourceIds', [])), WorkRevision.owner_id == actor.id, WorkRevision.company_id == actor.company_id))).all()
                text = '请根据以下已确认工作修订生成报告，调用 draft_report 保存草稿。禁止使用其他未确认内容。\n' + json.dumps({'kind': report.kind, 'period': report.period, 'periodEnd': report.period_end, 'confirmed': [{'revisionId': r.id, 'content': r.content} for r in sources]}, ensure_ascii=False)
                attachments, transcript, reply_to = [], '', None
        blocks = []
        for attachment in attachments:
            if attachment.kind == 'audio' and not transcript:
                transcript = await (asr_provider(context, attachment) if asr_provider else asr(context, attachment))
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
                raw = await asyncio.to_thread((settings.media_dir / attachment.id).read_bytes)
                _, resized = await asyncio.to_thread(image_input, raw)
                blocks.append({'type': 'image_url', 'image_url': {'url': data_url(resized, 'image/jpeg')}})
        if job.kind == 'message':
            context.source_revision = transcript_revision
        blocks.insert(0, {'type': 'text', 'text': f'原消息 ID：{job.target_id}\n' + (f'补充此前消息：{reply_to}\n' if reply_to else '') + text + ('\n语音转写（员工可纠正）：' + transcript if transcript else '')})
        if not model and not context.model_binding.get(context.model_purpose):
            raise ValueError('当前用途的模型尚未配置，请联系管理员；原始内容已保存')
        answer = await invoke_harness(context, checkpointer, blocks, model)
        async with sessions.begin() as db:
            live, actor = await lease(db, context)
            if job.kind == 'message':
                message = await owned(db, Message, job.target_id, actor, lock=True)
                message.reply = answer
                live.state = 'succeeded' if message.suggestions else 'awaiting_input'
            else:
                if not live.result.get('reportSaved'):
                    raise ValueError('报告没有生成有效草稿，请重试')
                live.state = 'succeeded'
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
                live.state = 'awaiting_retry' if live.request_started else 'failed'
                live.error, live.lease_until, live.updated_at = reason, None, now()
    finally:
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)


async def schedule_once(sessions, instant=None):
    instant = instant or now()
    async with sessions.begin() as db:
        companies = (await db.scalars(select(Company))).all()
        for company in companies:
            zone = ZoneInfo(company.rules['timezone'])
            local = instant.astimezone(zone)
            for kind in ('daily', 'weekly'):
                rule = company.rules[kind]
                if not rule['enabled'] or not rule['generateTime'] or local.weekday() not in rule['days']:
                    continue
                due = datetime.combine(local.date(), time.fromisoformat(rule['generateTime']), zone)
                if due > local or due <= company.rules_effective_at:
                    continue
                members = (await db.scalars(select(Member).where(Member.company_id == company.id, Member.active.is_(True)))).all()
                for member in members:
                    await ensure_report(db, member, kind, local.date(), scheduled=True)


async def maintenance(sessions, settings):
    async with sessions.begin() as db:
        old = (await db.scalars(select(Attachment).where(Attachment.message_id.is_(None), Attachment.created_at < now() - timedelta(hours=24)).with_for_update(skip_locked=True))).all()
        for attachment in old:
            (settings.media_dir / attachment.id).unlink(missing_ok=True)
            await db.delete(attachment)
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


async def main():
    settings = Settings()
    engine, sessions = database(settings)
    timer = asyncio.create_task(scheduler(sessions, settings))
    try:
        async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
            while True:
                job = await claim(sessions)
                if job:
                    await process_job(job, sessions, settings, saver)
                else:
                    await asyncio.sleep(1)
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
