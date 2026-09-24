from app.integrations.models.transport import ProviderError, normalize_url
from app.modules.members.models import Company
from app.modules.model_services.models import ModelRouting, ModelService, ModelServiceRevision
from app.modules.model_services.parameters import request_options
from app.modules.model_services.schemas import ServiceModel, parameters
from app.modules.model_services.service import current_revision, get_service, validate_choice, validate_master_key
from app.security.secrets import decrypt, encrypt
from sqlalchemy import select
from uuid import uuid4


async def bind_job(db, job, settings):
    refresh = job.kind == 'message' and job.result.get('refreshModelBinding', False)
    previous = job.model_binding
    if previous is not None and not refresh:
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
    if refresh:
        # Manual retries use the latest configuration when the worker starts.
        # Unchanged settings keep the checkpoint and completed node results.
        comparable = lambda value: {k: v for k, v in (value or {}).items() if k != 'attempt'}
        if comparable(previous) != comparable(binding):
            job.config_attempt += 1
            binding['attempt'] = job.config_attempt
        job.result = {k: v for k, v in job.result.items() if k != 'refreshModelBinding'}
    job.model_binding = binding
    return binding


async def resolve_bound(db, settings, company_id, binding, purpose):
    choice = binding.get(purpose)
    if not choice:
        raise ProviderError('not_configured', {'assistant': '工作助手', 'report': '报告模型', 'asr': '语音转写'}[purpose] + '尚未配置，请联系管理员；原始材料已保留')
    service = await db.scalar(select(ModelService).where(ModelService.id == choice['serviceId'], ModelService.company_id == company_id, ModelService.revoked.is_(False)))
    if not service:
        raise ProviderError('revoked', '模型配置已更新，请重试')
    rev = await db.scalar(select(ModelServiceRevision).where(ModelServiceRevision.id == choice['revisionId'], ModelServiceRevision.service_id == service.id, ModelServiceRevision.company_id == company_id))
    if not rev or not rev.credential:
        raise ProviderError('revoked', '模型配置已更新，请重试')
    model = next(m for m in rev.models if m['id'] == choice['modelId'])
    chosen = dict(model, selectedPresetId=choice.get('presetId'))
    config = {'baseUrl': rev.base_url, 'model': model['model'], 'protocol': model['protocol'], 'parameters': parameters(model['legacyParameters']) if 'legacyParameters' in model else request_options(chosen), 'streaming': choice['streaming'], 'language': model.get('language', '')}
    key = decrypt(settings.model_key_file, rev.credential, company_id, service.id, rev.revision)
    return config, key
