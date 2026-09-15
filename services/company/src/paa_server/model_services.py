"""Company-scoped revisions, routing, credential resolution and paid probe boundary."""
import asyncio
import hashlib
import json
from pathlib import Path
import time
from uuid import uuid4
from sqlalchemy import func, select, text

from .models import Company, Job, ModelCheck, ModelRouting, ModelService, ModelServiceRevision, ModelUsage, now
from .model_schemas import ServiceInput, ServiceModel, parameters
from .model_secrets import decrypt, encrypt, read_key
from .model_provider import ProviderError, catalog, chat, image_sample, normalize_url, request_options, safe_error, transcribe
from .service import problem, version

EMPTY_CHOICES = {'assistant': None, 'report': 'follow', 'asr': None}


def service_dto(row):
    return {'id': row.id, 'name': row.name, 'baseUrl': row.base_url, 'models': row.models, 'revision': row.revision, 'hasKey': True, 'updatedAt': row.updated_at.isoformat()}


async def get_service(db, company_id, identifier, *, lock=False):
    query = select(ModelService).where(ModelService.id == identifier, ModelService.company_id == company_id, ModelService.revoked.is_(False))
    row = await db.scalar(query.with_for_update() if lock else query)
    if not row:
        problem(404, '模型服务不存在或无权访问')
    return row


async def current_revision(db, service):
    return await db.scalar(select(ModelServiceRevision).where(ModelServiceRevision.service_id == service.id, ModelServiceRevision.revision == service.revision))


async def validate_master_key(db, settings):
    read_key(settings.model_key_file)
    # A syntactically valid replacement file must not silently establish a second
    # key lineage while an existing database backup still depends on the first.
    witness = await db.scalar(select(ModelServiceRevision).where(ModelServiceRevision.credential != '').limit(1))
    if witness:
        decrypt(settings.model_key_file, witness.credential, witness.company_id, witness.service_id, witness.revision)


async def save_service(db, settings, actor, body, identifier=None):
    await db.scalar(select(Company).where(Company.id == actor.company_id).with_for_update())
    url = normalize_url(body.baseUrl, settings)
    await validate_master_key(db, settings)
    row = await get_service(db, actor.company_id, identifier, lock=True) if identifier else None
    if row:
        version(row, body.expectedRevision)
        old = await current_revision(db, row)
        if not body.apiKey and url != row.base_url:
            problem(422, '更换地址后必须重新输入密钥')
        key = body.apiKey or decrypt(settings.model_key_file, old.credential, actor.company_id, row.id, old.revision)
        routing = await db.get(ModelRouting, actor.company_id)
        if routing:
            choices = routing.choices
            for purpose, choice in choices.items():
                if isinstance(choice, dict) and choice['serviceId'] == row.id:
                    validate_choice(body.models, choice, purpose)
        row.revision += 1
    else:
        if body.expectedRevision != 0:
            problem(409, '新增服务的版本无效')
        if not body.apiKey:
            problem(422, '请输入服务密钥')
        count = await db.scalar(select(func.count()).select_from(ModelService).where(ModelService.company_id == actor.company_id, ModelService.revoked.is_(False), ModelService.internal.is_(False)))
        if count >= 16:
            problem(422, '每家公司最多保存 16 家模型服务')
        key = body.apiKey
        row = ModelService(id=str(uuid4()), company_id=actor.company_id, revision=1)
        db.add(row)
    row.name, row.base_url, row.models, row.updated_at = body.name.strip(), url, [m.model_dump() for m in body.models], now()
    await db.flush()
    db.add(ModelServiceRevision(company_id=actor.company_id, service_id=row.id, revision=row.revision, name=row.name, base_url=url, models=row.models, credential=encrypt(settings.model_key_file, key, actor.company_id, row.id, row.revision)))
    await db.flush()
    return service_dto(row)


def validate_choice(models, choice, purpose):
    models = [m.model_dump() if isinstance(m, ServiceModel) else m for m in models]
    model = next((m for m in models if m['id'] == choice['modelId']), None)
    if not model or ((purpose == 'asr') != (model['protocol'] != 'chat')):
        problem(422, '所选模型不存在或协议不适用于该用途')
    if choice.get('presetId') and not any(p['id'] == choice['presetId'] for p in model['presets']):
        problem(422, '已分配的推理预设不存在，请先更改用途分配')
    return model


async def routing_dto(db, company_id, settings):
    row = await db.get(ModelRouting, company_id)
    company = await db.get(Company, company_id)
    environment = bool(not row and company.environment_models)
    return {'revision': row.revision if row else 0, 'source': 'environment' if environment else 'database', **(row.choices if row else EMPTY_CHOICES), 'environment': environment_summary(settings) if environment else None}


def environment_summary(settings):
    return {'assistant': {'baseUrl': settings.agent_base_url, 'model': settings.agent_model, 'hasKey': bool(settings.agent_key)}, 'asr': {'baseUrl': settings.asr_base_url, 'model': settings.asr_model, 'hasKey': bool(settings.asr_key)}}


async def save_routing(db, actor, body, settings):
    await db.scalar(select(Company).where(Company.id == actor.company_id).with_for_update())
    row = await db.get(ModelRouting, actor.company_id)
    if (row.revision if row else 0) != body.expectedRevision:
        problem(409, '用途配置已在其他页面更新，请读取最新版本', 'revision_conflict')
    choices = body.model_dump(exclude={'expectedRevision'})
    for purpose, choice in choices.items():
        if isinstance(choice, dict):
            service = await get_service(db, actor.company_id, choice['serviceId'])
            validate_choice(service.models, choice, purpose)
    if row:
        row.revision += 1
        row.choices = choices
    else:
        row = ModelRouting(company_id=actor.company_id, revision=1, choices=choices)
        db.add(row)
    await db.flush()
    return await routing_dto(db, actor.company_id, settings)


async def remove_service(db, actor, identifier, expected):
    await db.scalar(select(Company).where(Company.id == actor.company_id).with_for_update())
    service = await get_service(db, actor.company_id, identifier, lock=True)
    version(service, expected)
    routing = await db.get(ModelRouting, actor.company_id)
    affected = [purpose for purpose, choice in (routing.choices if routing else {}).items() if isinstance(choice, dict) and choice['serviceId'] == identifier]
    if affected:
        problem(409, '该服务正在用于 ' + '、'.join({'assistant': '工作助手', 'report': '报告', 'asr': '语音转写'}[p] for p in affected) + '，请先解除或更换用途')
    service.revoked = True
    # Keep non-sensitive provenance but remove all credential availability.
    revisions = (await db.scalars(select(ModelServiceRevision).where(ModelServiceRevision.service_id == service.id))).all()
    for rev in revisions:
        rev.credential = ''
    return {'deleted': True}


async def draft_config(db, actor, body, settings):
    url = normalize_url(body.baseUrl, settings)
    key = body.apiKey
    row = None
    if body.serviceId:
        row = await get_service(db, actor.company_id, body.serviceId)
        version(row, body.expectedRevision)
    if not key:
        if not row or url != row.base_url:
            problem(422, '请为当前服务地址输入密钥')
        rev = await current_revision(db, row)
        key = decrypt(settings.model_key_file, rev.credential, actor.company_id, row.id, rev.revision)
    payload = body.model_dump(exclude={'apiKey'})
    # Fingerprint uses a digest, never plaintext credential or reusable token.
    payload['credentialDigest'] = hashlib.sha256(key.encode()).hexdigest()
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    model = next((m.model_dump() for m in body.models if m.id == body.modelId), None)
    config = None
    if model:
        config = {'baseUrl': url, 'model': model['model'], 'protocol': model['protocol'], 'streaming': model['streaming'] if model['protocol'] == 'chat' else False, 'parameters': request_options(model), 'language': model['language']}
    return config, key, fingerprint


async def import_environment(db, actor, settings):
    company = await db.scalar(select(Company).where(Company.id == actor.company_id).with_for_update())
    if not company.environment_models or await db.get(ModelRouting, actor.company_id):
        problem(409, '当前公司没有可导入的环境配置，或已由数据库配置接管')
    selections, created = {}, []
    for purpose, url, key, model in [('assistant', settings.agent_base_url, settings.agent_key, settings.agent_model), ('asr', settings.asr_base_url, settings.asr_key, settings.asr_model)]:
        if not url or not key:
            selections[purpose] = None
            continue
        options = settings.agent_options or {'enable_thinking': False}
        entry = {'id': purpose, 'model': model, 'protocol': 'chat' if purpose == 'assistant' else 'qwen-asr', 'streaming': False, 'presets': [{'id': 'imported', 'name': '原环境参数', 'mode': 'advanced', 'parameters': options}] if purpose == 'assistant' else [], 'selectedPresetId': 'imported' if purpose == 'assistant' else None}
        # Imports remain explicit and only group credentials that are exactly equal.
        prior = next((x for x in created if x[0] == url and x[1] == key), None)
        if prior:
            saved = await save_service(db, settings, actor, ServiceInput(name=prior[2]['name'], baseUrl=url, apiKey=key, models=[*prior[2]['models'], entry], expectedRevision=prior[2]['revision']), prior[2]['id'])
        else:
            saved = await save_service(db, settings, actor, ServiceInput(name='原工作助手服务' if purpose == 'assistant' else '原语音服务', baseUrl=url, apiKey=key, models=[entry]))
            created.append((url, key, saved))
        selections[purpose] = {'serviceId': saved['id'], 'modelId': purpose, 'presetId': 'imported' if purpose == 'assistant' else None, 'streaming': False}
    if not any(selections.values()):
        problem(422, '原环境没有完整的服务地址和密钥，请直接添加服务')
    db.add(ModelRouting(company_id=actor.company_id, revision=1, choices={**selections, 'report': 'follow'}))
    await db.flush()
    return await routing_dto(db, actor.company_id, settings)


async def bind_job(db, job, settings):
    if job.model_binding is not None:
        return job.model_binding
    routing = await db.get(ModelRouting, job.company_id)
    company = await db.get(Company, job.company_id)
    purpose = 'report' if job.kind == 'report' else 'assistant'
    binding = {'attempt': job.config_attempt, 'routingRevision': routing.revision if routing else 0, 'source': 'database' if routing or not company.environment_models else 'environment'}
    for use in (purpose, 'asr') if purpose == 'assistant' else (purpose,):
        if routing:
            selection = routing.choices[use]
            if selection == 'follow':
                selection = routing.choices['assistant']
            if not selection:
                binding[use] = None
                continue
            service = await get_service(db, job.company_id, selection['serviceId'])
            rev = await current_revision(db, service)
            model = validate_choice(rev.models, selection, use)
            binding[use] = {'serviceId': service.id, 'revisionId': rev.id, 'revision': rev.revision, 'name': rev.name, 'modelId': model['id'], 'model': model['model'], 'protocol': model['protocol'], 'presetId': selection['presetId'], 'streaming': selection['streaming'] if use != 'asr' else False}
        elif company.environment_models:
            url, key, name = (settings.asr_base_url, settings.asr_key, settings.asr_model) if use == 'asr' else (settings.agent_base_url, settings.agent_key, settings.agent_model)
            if not url or not key:
                binding[use] = None
                continue
            await validate_master_key(db, settings)
            # A private immutable service revision snapshots legacy configuration too.
            environment_name = '环境语音快照' if use == 'asr' else '环境助手快照'
            service = ModelService(id=str(uuid4()), company_id=job.company_id, name=environment_name, base_url=normalize_url(url, settings), revision=1, models=[], revoked=False, internal=True)
            model = ServiceModel(id='legacy', model=name, protocol='qwen-asr' if use == 'asr' else 'chat', streaming=False, presets=[]).model_dump()
            model['legacyParameters'] = settings.agent_options or {'enable_thinking': False} if use != 'asr' else {}
            service.models = [model]
            candidates = (await db.scalars(select(ModelService).where(ModelService.company_id == job.company_id, ModelService.internal.is_(True), ModelService.revoked.is_(False), ModelService.base_url == service.base_url))).all()
            matched = None
            for candidate in candidates:
                candidate_rev = await current_revision(db, candidate)
                if candidate.models == service.models and decrypt(settings.model_key_file, candidate_rev.credential, job.company_id, candidate.id, candidate_rev.revision) == key:
                    matched = candidate_rev
                    service = candidate
                    break
            if matched:
                binding[use] = {'serviceId': service.id, 'revisionId': matched.id, 'revision': matched.revision, 'name': matched.name, 'modelId': 'legacy', 'model': name, 'protocol': model['protocol'], 'presetId': None, 'streaming': False, 'environmentSnapshot': True}
                continue
            db.add(service)
            await db.flush()
            rev = ModelServiceRevision(company_id=job.company_id, service_id=service.id, revision=1, name=environment_name, base_url=service.base_url, models=[model], credential=encrypt(settings.model_key_file, key, job.company_id, service.id, 1))
            db.add(rev)
            await db.flush()
            binding[use] = {'serviceId': service.id, 'revisionId': rev.id, 'revision': 1, 'name': rev.name, 'modelId': 'legacy', 'model': name, 'protocol': model['protocol'], 'presetId': None, 'streaming': False, 'environmentSnapshot': True}
        else:
            binding[use] = None
    job.model_binding = binding
    return binding


async def resolve_bound(db, settings, company_id, binding, purpose):
    choice = binding.get(purpose)
    if not choice:
        raise ProviderError('not_configured', {'assistant': '工作助手', 'report': '报告模型', 'asr': '语音转写'}[purpose] + '尚未配置，请联系管理员；原始材料已保留')
    service = await db.scalar(select(ModelService).where(ModelService.id == choice['serviceId'], ModelService.company_id == company_id, ModelService.revoked.is_(False)))
    if not service:
        raise ProviderError('revoked', '原模型配置已撤销，请选择使用当前配置重新处理')
    rev = await db.scalar(select(ModelServiceRevision).where(ModelServiceRevision.id == choice['revisionId'], ModelServiceRevision.service_id == service.id, ModelServiceRevision.company_id == company_id))
    if not rev or not rev.credential:
        raise ProviderError('revoked', '原模型配置已撤销，请选择使用当前配置重新处理')
    model = next(m for m in rev.models if m['id'] == choice['modelId'])
    chosen = dict(model, selectedPresetId=choice.get('presetId'))
    config = {'baseUrl': rev.base_url, 'model': model['model'], 'protocol': model['protocol'], 'parameters': parameters(model['legacyParameters']) if 'legacyParameters' in model else request_options(chosen), 'streaming': choice['streaming'], 'language': model.get('language', '')}
    key = decrypt(settings.model_key_file, rev.credential, company_id, service.id, rev.revision)
    return config, key


async def reserve_probe(sessions, settings, actor):
    async with sessions.begin() as db:
        await db.scalar(select(Company).where(Company.id == actor.company_id).with_for_update())
        count = await db.scalar(select(func.count()).select_from(ModelUsage).where(ModelUsage.company_id == actor.company_id, ModelUsage.created_at >= now().replace(hour=0, minute=0, second=0, microsecond=0)))
        if count >= settings.daily_calls:
            raise ProviderError('quota', '今天的模型调用额度已用完')
        usage = ModelUsage(company_id=actor.company_id, owner_id=actor.id, job_id=None, kind='admin_test')
        db.add(usage)
        await db.flush()
        return usage.id


async def probe(request_db, sessions, settings, actor, body, config, key, fingerprint):
    started = time.monotonic()
    result = {'draftVersion': body.draftVersion, 'fingerprint': fingerprint, 'service': body.name, 'model': config['model'] if config else '', 'revision': body.expectedRevision, 'purpose': body.purpose, 'time': now().isoformat(), 'checks': [], 'usage': None}
    names = ['语音转写'] if body.purpose == 'asr' else ['文字', *(['图片'] if body.purpose == 'assistant' else []), '工具往返']
    result['checks'] = [{'name': name, 'state': 'untested'} for name in names]
    current = 0
    totals = {'inputTokens': 0, 'outputTokens': 0}
    known_usage = False
    async def request_key():
        if not body.serviceId:
            return key
        # Read scalar columns on the existing request connection so each call
        # sees committed revocations without cached ORM rows or extra pool use.
        # A later edit keeps this revision valid; never resolve the latest one.
        credential = await request_db.scalar(select(ModelServiceRevision.credential).join(ModelService, ModelService.id == ModelServiceRevision.service_id).where(
            ModelService.id == body.serviceId,
            ModelService.company_id == actor.company_id,
            ModelService.revoked.is_(False),
            ModelServiceRevision.company_id == actor.company_id,
            ModelServiceRevision.revision == body.expectedRevision,
        ))
        if not credential:
            raise ProviderError('revoked', '本次检测引用的模型服务已撤销，请重新选择服务')
        saved_key = decrypt(settings.model_key_file, credential, actor.company_id, body.serviceId, body.expectedRevision)
        return key if body.apiKey else saved_key

    async def request(messages, **kw):
        nonlocal known_usage
        usage_id = await reserve_probe(sessions, settings, actor)
        outgoing_key = await request_key()
        response = await asyncio.wait_for(chat(settings, config, outgoing_key, messages, max_tokens=256, **kw), 60)
        usage = response.get('usage') or {}
        if usage:
            known_usage = True
            totals['inputTokens'] += int(usage.get('prompt_tokens', 0))
            totals['outputTokens'] += int(usage.get('completion_tokens', 0))
            async with sessions.begin() as db:
                record = await db.get(ModelUsage, usage_id)
                record.input_tokens, record.output_tokens = int(usage.get('prompt_tokens', 0)), int(usage.get('completion_tokens', 0))
        return response['choices'][0]['message']
    try:
        if not config or ((body.purpose == 'asr') != (config['protocol'] != 'chat')):
            raise ProviderError('protocol', '请选择适用于当前用途的模型协议')
        if body.purpose == 'asr':
            usage_id = await reserve_probe(sessions, settings, actor)
            speech = (Path(__file__).parent / 'assets/probe-zh.wav').read_bytes()
            outgoing_key = await request_key()
            transcript, usage = await asyncio.wait_for(transcribe(settings, config, outgoing_key, speech), 60)
            cleaned = ''.join(c for c in transcript if c.isalnum())
            if not all(word in cleaned for word in ('今天', '工作', '完成')):
                raise ProviderError('invalid_response', '语音接口返回了文字，但未识别固定中文样本的主要内容')
            result['checks'][0]['state'] = 'passed'
            result['usage'] = usage
            if usage:
                async with sessions.begin() as db:
                    record = await db.get(ModelUsage, usage_id)
                    record.input_tokens, record.output_tokens = usage.get('prompt_tokens', 0), usage.get('completion_tokens', 0)
        else:
            answer = await request([{'role': 'user', 'content': '这是连通性测试。只回复：测试成功'}])
            if '测试成功' not in (answer.get('content') or ''):
                raise ProviderError('invalid_response', '模型没有按要求完成文字样本')
            result['checks'][current]['state'] = 'passed'; current += 1
            if body.purpose == 'assistant':
                answer = await request([{'role': 'user', 'content': [{'type': 'text', 'text': '这张图片是什么颜色？只回答颜色。'}, {'type': 'image_url', 'image_url': {'url': image_sample()}}]}])
                if '红' not in (answer.get('content') or ''):
                    raise ProviderError('invalid_response', '模型未正确识别固定图片，不能确认图片能力')
                result['checks'][current]['state'] = 'passed'; current += 1
            tools = [{'type': 'function', 'function': {'name': 'probe_echo', 'description': 'Return the supplied value for this capability test; no business writes.', 'parameters': {'type': 'object', 'properties': {'value': {'type': 'string'}}, 'required': ['value'], 'additionalProperties': False}}}]
            messages = [{'role': 'user', 'content': '调用 probe_echo，value 为 测试成功，然后根据工具返回值只回答测试成功。'}]
            answer = await request(messages, tools=tools, tool_choice={'type': 'function', 'function': {'name': 'probe_echo'}})
            calls = answer.get('tool_calls') or []
            if len(calls) != 1 or calls[0]['function']['name'] != 'probe_echo' or json.loads(calls[0]['function']['arguments']) != {'value': '测试成功'}:
                raise ProviderError('invalid_response', '模型没有返回所要求的完整工具调用')
            messages += [answer, {'role': 'tool', 'tool_call_id': calls[0]['id'], 'content': '测试成功'}]
            answer = await request(messages, tools=tools)
            if answer.get('tool_calls') or '测试成功' not in (answer.get('content') or ''):
                raise ProviderError('invalid_response', '模型没有根据工具结果完成回复')
            result['checks'][current]['state'] = 'passed'
    except Exception as error:
        failure = safe_error(error)
        result['checks'][current].update(state='failed', code=failure.code, message=str(failure), status=failure.status)
    result['elapsedMs'] = round((time.monotonic() - started) * 1000)
    if known_usage:
        result['usage'] = totals
    async with sessions.begin() as db:
        db.add(ModelCheck(company_id=actor.company_id, actor_id=actor.id, fingerprint=fingerprint, result=result))
    return result


def register_routes(app, ADMIN, DB, settings, sessions):
    from .model_schemas import ConfigRequest, RoutingInput, ServiceInput
    from .schemas import Revision
    from fastapi import Request

    @app.get('/api/v1/settings/model-services')
    async def list_services(actor=ADMIN, db=DB):
        rows = (await db.scalars(select(ModelService).where(ModelService.company_id == actor.company_id, ModelService.revoked.is_(False), ModelService.internal.is_(False)).order_by(ModelService.created_at))).all()
        return {'services': [service_dto(s) for s in rows], 'routing': await routing_dto(db, actor.company_id, settings)}

    @app.post('/api/v1/settings/model-services', status_code=201)
    async def create(body: ServiceInput, actor=ADMIN, db=DB):
        return await save_service(db, settings, actor, body)

    @app.post('/api/v1/settings/model-services/import-environment')
    async def import_config(actor=ADMIN, db=DB):
        return await import_environment(db, actor, settings)

    @app.post('/api/v1/settings/model-services/models')
    async def models(body: ConfigRequest, actor=ADMIN, db=DB):
        _, key, fingerprint = await draft_config(db, actor, body, settings)
        if not await db.scalar(text('SELECT pg_try_advisory_xact_lock(hashtextextended(:company, 9))'), {'company': actor.company_id}):
            problem(409, '公司已有目录或检测请求正在进行，请稍后再试')
        try:
            result = await catalog(settings, body.baseUrl, key)
        except ProviderError:
            raise
        except Exception as error:
            raise safe_error(error) from None
        return {**result, 'draftVersion': body.draftVersion, 'fingerprint': fingerprint}

    @app.post('/api/v1/settings/model-services/test')
    async def test(body: ConfigRequest, request: Request, actor=ADMIN, db=DB):
        config, key, fingerprint = await draft_config(db, actor, body, settings)
        if not await db.scalar(text('SELECT pg_try_advisory_xact_lock(hashtextextended(:company, 9))'), {'company': actor.company_id}):
            problem(409, '公司已有目录或检测请求正在进行，请稍后再试')
        # Reuse the request transaction for the lock; a second connection here
        # would exhaust the small production pool under concurrent probes.
        try:
            result = await asyncio.wait_for(probe(db, sessions, settings, actor, body, config, key, fingerprint), 180)
        except asyncio.TimeoutError:
            raise ProviderError('timeout', '检测超过总时限，请核对调用记录后再试') from None
        return {**result, 'requestId': request.state.request_id}

    @app.get('/api/v1/settings/model-services/{identifier}')
    async def read(identifier: str, actor=ADMIN, db=DB):
        row = await get_service(db, actor.company_id, identifier)
        if row.internal:
            problem(404, '模型服务不存在或无权访问')
        return service_dto(row)

    @app.patch('/api/v1/settings/model-services/{identifier}')
    async def update(identifier: str, body: ServiceInput, actor=ADMIN, db=DB):
        if (await get_service(db, actor.company_id, identifier)).internal:
            problem(404, '模型服务不存在或无权访问')
        return await save_service(db, settings, actor, body, identifier)

    @app.delete('/api/v1/settings/model-services/{identifier}')
    async def remove(identifier: str, body: Revision, actor=ADMIN, db=DB):
        return await remove_service(db, actor, identifier, body.expectedRevision)

    @app.get('/api/v1/settings/model-routing')
    async def read_routing(actor=ADMIN, db=DB):
        return await routing_dto(db, actor.company_id, settings)

    @app.put('/api/v1/settings/model-routing')
    async def write_routing(body: RoutingInput, actor=ADMIN, db=DB):
        return await save_routing(db, actor, body, settings)
