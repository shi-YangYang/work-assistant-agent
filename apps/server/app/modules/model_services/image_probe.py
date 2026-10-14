"""Explicit admin image probe; external generation never holds a DB connection."""
import asyncio
import time
from datetime import timedelta
from sqlalchemy import select
from app.core.errors import problem
from app.db.base import now
from app.integrations.models.images import wan, results, sizes
from app.integrations.models.transport import ProviderError, safe_error
from app.modules.members.models import Member
from app.modules.model_services.models import ModelCheck, ModelUsage, ModelService, ModelServiceRevision
from app.modules.model_services.usage.usage import RequestRecord, usage_fields
from app.security.locks import company_lock
from app.security.secrets import decrypt


async def image_probe(sessions, settings, actor, body, config, key, fingerprint):
    started = time.monotonic()
    result = {'draftVersion': body.draftVersion, 'fingerprint': fingerprint, 'service': body.name, 'model': config['model'] if config else '',
        'revision': body.expectedRevision, 'purpose': 'image', 'time': now().isoformat(), 'checks': [{'name': '图片生成与读取', 'state': 'untested'}], 'usage': None}
    async def authorize():
        async with sessions.begin() as db:
            member = await db.get(Member, actor.id)
            if not member or not member.active or member.role != 'admin' or member.company_id != actor.company_id:
                problem(403, '当前账号无法继续检测模型配置')
            if body.serviceId:
                credential = await db.scalar(select(ModelServiceRevision.credential).join(ModelService, ModelService.id == ModelServiceRevision.service_id).where(
                    ModelService.id == body.serviceId, ModelService.company_id == actor.company_id, ModelService.revoked.is_(False),
                    ModelServiceRevision.revision == body.expectedRevision))
                if not credential:
                    raise ProviderError('revoked', '本次检测引用的模型服务已撤销，请重新选择服务')
                return key if body.apiKey else decrypt(settings.model_key_file, credential, actor.company_id, body.serviceId, body.expectedRevision)
            return key
    async with sessions.begin() as db:
        await company_lock(db, actor.company_id)
        active = await db.scalar(select(ModelUsage.id).where(ModelUsage.company_id == actor.company_id, ModelUsage.kind == 'image',
            ModelUsage.job_id.is_(None), ModelUsage.status.in_(('reserved', 'running')), ModelUsage.created_at > now() - timedelta(minutes=6)))
        if active:
            problem(409, '图片配置测试正在进行，请等待本次结果')
        usage = ModelUsage(company_id=actor.company_id, owner_id=actor.id, kind='image', job_id=None,
            **usage_fields({'serviceId': body.serviceId, 'name': body.name, 'model': result['model']}))
        db.add(usage)
        await db.flush()
        usage_id = usage.id
    record = RequestRecord(sessions, usage_id)
    try:
        if not config:
            raise ProviderError('protocol', '请选择图片模型', sent=False)
        wan.endpoint(settings, config)
        size = sizes.normalize(config=config)
        outgoing = await authorize()
        await record.event('started')
        async with asyncio.timeout(300):
            prompt = '一只蓝色的小鸟，纯白背景，简洁插画，无文字。'
            if wan.synchronous(config):
                response = await wan.generate_sync(settings, config, outgoing, prompt, size)
                result['providerRequestId'] = response.get('request_id', '')
                state = 'SUCCEEDED'
            else:
                task_id, request_id = await wan.submit(settings, config, outgoing, prompt, size)
                result['providerRequestId'] = request_id
                while True:
                    response = await wan.query(settings, config, await authorize(), task_id)
                    state = response['output']['task_status']
                    if state not in ('PENDING', 'RUNNING'):
                        break
                    await asyncio.sleep(1)
            if state != 'SUCCEEDED':
                raise ProviderError('image_failed', '图片测试未生成成功，请核对模型权限或调整配置')
            urls = wan.images(response)
            if not urls:
                raise ProviderError('image_empty', '图片服务未返回图片')
            await authorize()
            _, metadata = await results.download(urls[0])
            await authorize()
            result['checks'][0].update(state='passed', message=f"PNG · {metadata['width']} × {metadata['height']}")
            usage = response.get('usage') or {}
            tokens = {k: usage[k] for k in ('input_tokens', 'output_tokens', 'total_tokens') if isinstance(usage.get(k), int)}
            result['usage'] = tokens or None
            await record.event('usage', {'prompt_tokens': usage.get('input_tokens'), 'completion_tokens': usage.get('output_tokens')})
        await record.finish()
    except BaseException as error:
        await record.finish(error)
        if isinstance(error, asyncio.CancelledError):
            raise
        failure = safe_error(error)
        result['checks'][0].update(state='failed', code=failure.code, message=str(failure))
    result['elapsedMs'] = round((time.monotonic() - started) * 1000)
    async with sessions.begin() as db:
        db.add(ModelCheck(company_id=actor.company_id, actor_id=actor.id, fingerprint=fingerprint, result=result))
    return result
