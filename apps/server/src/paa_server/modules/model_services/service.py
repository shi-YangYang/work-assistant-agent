from paa_server.core.errors import problem
from paa_server.core.versions import version
from paa_server.db.base import now
from paa_server.integrations.models.transport import normalize_url
from paa_server.modules.members.models import Company
from paa_server.modules.model_services.models import ModelRouting, ModelService, ModelServiceRevision
from paa_server.modules.model_services.schemas import ServiceInput, ServiceModel
from paa_server.security.secrets import decrypt, encrypt, read_key
from sqlalchemy import func, select
from uuid import uuid4

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
