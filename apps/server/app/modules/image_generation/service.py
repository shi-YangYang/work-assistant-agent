"""Short durable claims surround all external I/O; ambiguous creates never replay."""
import asyncio
import time
from copy import deepcopy
from sqlalchemy import select
from app.core.digests import digest
from app.core.errors import problem
from app.db.base import now
from app.integrations.models.images import wan, results, sizes
from app.integrations.models.transport import ProviderError, safe_error
from app.modules.deliverables.models import DeliverableRevision
from app.modules.deliverables.serializers import detail
from app.modules.deliverables.service import save
from app.modules.executions.files import persist_file
from app.modules.executions.quota import lock_storage, reserve
from app.modules.executions.sources import check_sources, task_sources
from app.modules.image_generation.models import ImageGeneration
from app.modules.image_generation.files import checked_files, unchanged
from app.modules.messages.models import Message
from app.modules.model_services.bindings import resolve_bound
from app.modules.model_services.models import ModelUsage
from app.modules.model_services.usage.usage import RequestRecord, usage_fields
from app.security.ownership import owned
from app.tasks.context import LostLease
from app.tasks.feedback.feedback_state import update_feedback
from app.tasks.feedback.image_feedback import update as update_image
from app.tasks.lease import lease


async def authorized(db, context, row):
    job, actor = await lease(db, context)
    if row.owner_id != actor.id or row.company_id != actor.company_id or row.job_id != job.id or row.message_id != job.target_id:
        problem(403, '图片操作不可访问')
    await check_sources(db, actor, row.sources)
    config, key = await resolve_bound(db, context.settings, actor.company_id, row.binding, 'image')
    wan.endpoint(context.settings, config)
    return job, actor, config, key


async def claim(context, prompt, title, operation, size=None, *, intent=None, variant=0):
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        if job.kind != 'message':
            problem(422, '只有会话可以生成图片')
        message = await owned(db, Message, job.target_id, actor)
        previous = await db.scalar(select(ImageGeneration).where(ImageGeneration.message_id == message.id,
            ImageGeneration.operation == operation).with_for_update())
        # Recovery normalizes against the operation's frozen revision, never a
        # newly selected company model or a refreshed job binding.
        binding = deepcopy(previous.binding if previous else job.model_binding or {})
        config, key = await resolve_bound(db, context.settings, actor.company_id, binding, 'image')
        wan.endpoint(context.settings, config)
        if intent is not None:
            size = sizes.normalize(config=config, **intent)
        wire_size = sizes.wire_size(config, size)
        if wire_size and '*' in wire_size:
            width, height = map(int, wire_size.split('*'))
            update_image(job, operation, width=width, height=height)
        fingerprint = digest({'prompt': ' '.join(prompt.split()), 'size': sizes.wire_size(config, size),
                              **({'variant': variant} if variant else {})})
        row = previous or await db.scalar(select(ImageGeneration).where(ImageGeneration.message_id == message.id,
            ImageGeneration.fingerprint == fingerprint).with_for_update())
        if row:
            await authorized(db, context, row)
            if row.fingerprint != fingerprint:
                return row, {'state': 'conflict', 'code': 'image_operation_used',
                             'recovery': {'owner': 'none', 'nextAction': 'stop'},
                             'message': '该图片操作已使用，请复用原结果；如需另一张图片，请在新消息明确重新生成。'}
            recoverable = bool(row.task_id or row.provider_result)
            if row.state in ('succeeded', 'failed', 'cancelled') or row.state == 'unknown' and not recoverable:
                return row, row.result
            if row.state == 'submitting':
                if row.fence != context.fence:
                    row.state = 'unknown'
                    row.result = {'state': 'unknown', 'message': '上次图片请求结果尚未确认，已停止自动重发；请核对后再决定是否重新生成。'}
                    return row, row.result
                return row, {'state': 'running', 'message': '同一图片请求正在处理中，请等待已有操作。'}
            if row.state in ('polling', 'downloading') and row.fence == context.fence:
                return row, {'state': 'running', 'message': '图片正在处理中，已复用原请求。'}
            if not recoverable:
                row.state = 'unknown'
                row.result = {'state': 'unknown', 'message': '上次图片请求没有可恢复的回执，已停止自动重发。'}
                return row, row.result
            row.fence, row.state, row.updated_at = context.fence, 'polling' if not row.files else 'publishing', now()
            if recoverable:
                usage = await db.get(ModelUsage, row.usage_id)
                if usage.status in ('unknown', 'failed'):
                    # Resume the same provider call, preserving its original start.
                    usage.status, usage.finished_at = 'running', None
                    usage.error_code = usage.error_message = None
                    usage.job_fence = context.fence
            return row, None
        unresolved = await db.scalar(select(ImageGeneration).where(ImageGeneration.message_id == message.id, ImageGeneration.state.in_(('submitting', 'unknown'))))
        if unresolved:
            return unresolved, {'state': 'unknown', 'message': '本条消息已有尚未确认的图片请求，不再提交新请求；请等待或核对原结果。'}
        sources = await task_sources(db, actor, job, context, [])
        usage = ModelUsage(company_id=actor.company_id, owner_id=actor.id, job_id=job.id, kind='image',
            **usage_fields(binding.get('image'), attempt=job.config_attempt, fence=job.fence))
        db.add(usage)
        await db.flush()
        row = ImageGeneration(company_id=actor.company_id, owner_id=actor.id, job_id=job.id, conversation_id=message.conversation_id,
            message_id=message.id, operation=operation, fingerprint=fingerprint, fence=job.fence, binding=binding,
            request={'prompt': prompt, 'size': size, 'title': title}, sources=sources, state='submitting', usage_id=usage.id)
        db.add(row)
        await db.flush()
        return row, None


async def credentials(context, identifier):
    async with context.sessions.begin() as db:
        row = await db.get(ImageGeneration, identifier)
        _, _, config, key = await authorized(db, context, row)
        if row.fence != context.fence:
            raise LostLease()
        return config, key


async def set_result(context, identifier, state, value, task_id=None, provider_result=None):
    async with context.sessions.begin() as db:
        row = await db.scalar(select(ImageGeneration).where(ImageGeneration.id == identifier).with_for_update())
        if task_id and not row.task_id:
            row.task_id = task_id
        if provider_result and not row.provider_result:
            row.provider_result = deepcopy(provider_result)
            row.request_id = provider_result.get('request_id')
        # Store external facts after lease loss; this cannot publish a file or
        # overwrite a new worker's claim. Known IDs or sync receipts can resume.
        if row.fence == context.fence and row.state != 'succeeded':
            row.state, row.result, row.updated_at = state, value, now()


async def publish(context, identifier):
    async with context.sessions() as db:
        snapshot = deepcopy((await db.get(ImageGeneration, identifier)).files)
    checked = await asyncio.to_thread(checked_files, context.settings, snapshot)
    async with context.sessions.begin() as db:
        await lease(db, context)
        row = await db.scalar(select(ImageGeneration).where(ImageGeneration.id == identifier).with_for_update())
        job, actor, _, _ = await authorized(db, context, row)
        if row.fence != context.fence:
            raise LostLease()
        if row.result.get('delivery'):
            return row.result
        if row.files != snapshot:
            raise ProviderError('image_cache', '图片文件状态已更新，请重试读取原结果')
        await lock_storage(db)
        if not unchanged(checked):
            row.files, row.state, row.result, row.updated_at = [], 'polling', {}, now()
            return None
        message = await owned(db, Message, job.target_id, actor)
        used = set((await db.scalars(select(DeliverableRevision.step).where(DeliverableRevision.message_id == message.id))).all())
        step = next((step for step in range(1, 9) if step not in used), None)
        if step is None:
            problem(409, '本条消息的成果数量已达上限；图片已保留，请重试读取原结果。')
        item, record = await save(db, actor, message, job, {'title': row.request['title'], 'body': f'已生成 {len(row.files)} 张图片。'}, step=step, files=row.files)
        value = {'state': 'succeeded', 'operationId': row.id, 'imageCount': len(row.files), 'delivery': await detail(db, actor, item, record)}
        if row.result.get('partial'):
            value['message'] = '已交付可用图片，部分返回文件未能保存；没有重新生成。'
        row.state, row.result, row.updated_at = 'succeeded', value, now()
        context.deliverable_reads[item.id] = record.revision
        job.result = {**job.result, 'deliverableReads': {**job.result.get('deliverableReads', {}), item.id: record.revision},
                      'imageDeliveryCount': job.result.get('imageDeliveryCount', 0) + len(row.files)}
        update_image(job, row.operation, state='ready', deliverableId=item.id, revision=record.revision)
        update_feedback(job)
        return value


def validate_input(prompt, title, operation):
    if type(operation) is not int or not 1 <= operation <= 4:
        raise ProviderError('image_input', '每条消息最多生成 4 张图片，请使用 1～4 的操作编号；如需更多图片，请另发一条消息。', sent=False)
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 5000 or not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise ProviderError('image_input', '请提供 5000 字以内的画面描述及有效标题', sent=False)


async def generate(context, *, prompt, title='生成图片', operation=1, width=None, height=None, aspect='', resolution='', use='', variant=0):
    validate_input(prompt, title, operation)
    row, existing = await claim(context, prompt.strip(), title.strip(), operation, intent={
        'width': width, 'height': height, 'aspect': aspect, 'resolution': resolution, 'use': use}, variant=variant)
    if existing is not None:
        return existing
    record = RequestRecord(context.sessions, row.usage_id)
    identifier, task_id = row.id, row.task_id
    provider_result = deepcopy(row.provider_result or {})
    try:
        if row.files:
            cached = await publish(context, identifier)
            if cached is not None:
                return cached
        if not task_id and not provider_result:
            config, key = await credentials(context, identifier)
            await record.event('started')
            if wan.synchronous(config):
                provider_result = await wan.generate_sync(context.settings, config, key, row.request['prompt'], row.request['size'])
                await set_result(context, identifier, 'downloading', {}, provider_result=provider_result)
            else:
                task_id, request_id = await wan.submit(context.settings, config, key, row.request['prompt'], row.request['size'])
                async with context.sessions.begin() as db:
                    saved = await db.scalar(select(ImageGeneration).where(ImageGeneration.id == identifier).with_for_update())
                    # Persist external facts even after lease changes; publication
                    # independently requires the current lease and authorization.
                    saved.task_id, saved.request_id = task_id, request_id
                    if saved.fence == context.fence:
                        saved.state = 'polling'
        deadline = min(context.node_deadline or time.time() + 300, time.time() + 300)
        result, state = provider_result, 'SUCCEEDED'
        while not provider_result:
            config, key = await credentials(context, identifier)
            try:
                result = await wan.query(context.settings, config, key, task_id)
            except ProviderError as error:
                if error.status in (404, 410):
                    raise ProviderError('image_expired', '原图片任务已过期或不可用，无法恢复；没有重新生成', error.status) from None
                raise
            state = result['output']['task_status']
            if state not in ('PENDING', 'RUNNING'):
                break
            if time.time() + 1 >= deadline:
                raise ProviderError('timeout', '图片仍在生成，重试会查询原任务，不重复生成')
            await asyncio.sleep(1)
        if state != 'SUCCEEDED':
            failure = safe_error(ProviderError('image_failed', '图片生成未完成，请调整需求后再试'))
            from app.integrations.models.transport import structured_error
            failure = structured_error(result['output']) or failure
            value = {'state': 'cancelled' if state == 'CANCELED' else 'failed', 'message': str(failure)}
            await set_result(context, identifier, value['state'], value)
            await record.finish(failure)
            return value
        usage = result.get('usage') or {}
        await record.event('usage', {'prompt_tokens': usage.get('input_tokens'), 'completion_tokens': usage.get('output_tokens')})
        await record.finish()
        urls = wan.images(result)
        if not urls:
            raise ProviderError('image_empty', '图片服务未返回可用图片，请调整需求后重新发送')
        await set_result(context, identifier, 'downloading', {})
        payloads, failures = [], []
        for index, url in enumerate(urls):
            await credentials(context, identifier)
            try:
                data, metadata = await results.download(url)
                metadata['name'] = f'image-{index + 1}.png'
                if sum(len(item[0]) for item in payloads) + len(data) > results.MAX_BYTES:
                    raise ProviderError('image_format', '返回图片总大小超过文件限制')
                payloads.append((data, metadata))
            except Exception as error:
                failures.append(safe_error(error))
        if not payloads:
            raise failures[0]
        async with context.sessions.begin() as db:
            await lease(db, context)
            saved = await db.scalar(select(ImageGeneration).where(ImageGeneration.id == identifier).with_for_update())
            _, actor, _, _ = await authorized(db, context, saved)
            if saved.fence != context.fence:
                raise LostLease()
            await reserve(db, context.settings, actor, sum(len(data) for data, _ in payloads))
            saved.files = [persist_file(context.settings, identifier, metadata, data, saved.sources) for data, metadata in payloads]
            saved.state, saved.result, saved.updated_at = 'publishing', {'partial': bool(failures)}, now()
        published = await publish(context, identifier)
        if published is None:
            raise ProviderError('image_cache', '图片文件已不可用；重试会读取原任务，不重新生成')
        return published
    except (asyncio.CancelledError, LostLease):
        # No image can be published without the current lease. A known task is
        # read-only recoverable by a later worker; unknown creates stay unknown.
        if provider_result:
            await asyncio.shield(set_result(context, identifier, 'retryable', {'state': 'retryable', 'message': '图片处理已中断，重试会读取原结果'}, provider_result=provider_result))
        await asyncio.shield(record.finish(ProviderError('interrupted', '图片处理已中断')))
        raise
    except Exception as error:
        failure = safe_error(error)
        state = ('failed' if failure.code in ('image_expired', 'image_empty') else 'retryable' if task_id or provider_result else 'failed' if failure.sent is False or failure.status is not None else 'unknown')
        value = {'state': state, 'operationId': identifier, 'message': str(failure)}
        await set_result(context, identifier, state, value, task_id=task_id, provider_result=provider_result)
        await record.finish(ProviderError('interrupted', str(failure)) if state == 'unknown' else failure)
        return value
