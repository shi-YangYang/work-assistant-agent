import asyncio
from fastapi import APIRouter, Request
from app.core.errors import problem
from app.core.schemas import Revision
from app.http.dependencies import ADMIN, DB, SETTINGS
from app.integrations.models.catalog import catalog
from app.integrations.models.transport import ProviderError, safe_error
from app.modules.model_services.drafts import draft_config
from app.modules.model_services.models import ModelService
from app.modules.model_services.probes import probe
from app.modules.model_services.schemas import ConfigRequest, RoutingInput, ServiceInput
from app.modules.model_services.service import get_service, import_environment, remove_service, routing_dto, save_routing, save_service, service_dto
from sqlalchemy import select, text

router = APIRouter()


@router.get('/api/v1/settings/model-services')
async def list_services(actor=ADMIN, db=DB, settings=SETTINGS):
    rows = (await db.scalars(select(ModelService).where(ModelService.company_id == actor.company_id, ModelService.revoked.is_(False), ModelService.internal.is_(False)).order_by(ModelService.created_at))).all()
    return {'services': [service_dto(s) for s in rows], 'routing': await routing_dto(db, actor.company_id, settings)}


@router.post('/api/v1/settings/model-services', status_code=201)
async def create(body: ServiceInput, actor=ADMIN, db=DB, settings=SETTINGS):
    return await save_service(db, settings, actor, body)


@router.post('/api/v1/settings/model-services/import-environment')
async def import_config(actor=ADMIN, db=DB, settings=SETTINGS):
    return await import_environment(db, actor, settings)


@router.post('/api/v1/settings/model-services/models')
async def models(body: ConfigRequest, actor=ADMIN, db=DB, settings=SETTINGS):
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


@router.post('/api/v1/settings/model-services/test')
async def test(body: ConfigRequest, request: Request, actor=ADMIN, db=DB):
    config, key, fingerprint = await draft_config(db, actor, body, request.app.state.settings)
    if not await db.scalar(text('SELECT pg_try_advisory_xact_lock(hashtextextended(:company, 9))'), {'company': actor.company_id}):
        problem(409, '公司已有目录或检测请求正在进行，请稍后再试')
    # Reuse the request transaction for the lock; a second connection here
    # would exhaust the small production pool under concurrent probes.
    try:
        result = await asyncio.wait_for(probe(db, request.app.state.sessions, request.app.state.settings, actor, body, config, key, fingerprint), 180)
    except asyncio.TimeoutError:
        raise ProviderError('timeout', '检测超过总时限，请核对调用记录后再试') from None
    return {**result, 'requestId': request.state.request_id}


@router.get('/api/v1/settings/model-services/{identifier}')
async def read(identifier: str, actor=ADMIN, db=DB):
    row = await get_service(db, actor.company_id, identifier)
    if row.internal:
        problem(404, '模型服务不存在或无权访问')
    return service_dto(row)


@router.patch('/api/v1/settings/model-services/{identifier}')
async def update(identifier: str, body: ServiceInput, actor=ADMIN, db=DB, settings=SETTINGS):
    if (await get_service(db, actor.company_id, identifier)).internal:
        problem(404, '模型服务不存在或无权访问')
    return await save_service(db, settings, actor, body, identifier)


@router.delete('/api/v1/settings/model-services/{identifier}')
async def remove(identifier: str, body: Revision, actor=ADMIN, db=DB):
    return await remove_service(db, actor, identifier, body.expectedRevision)


@router.get('/api/v1/settings/model-routing')
async def read_routing(actor=ADMIN, db=DB, settings=SETTINGS):
    return await routing_dto(db, actor.company_id, settings)


@router.put('/api/v1/settings/model-routing')
async def write_routing(body: RoutingInput, actor=ADMIN, db=DB, settings=SETTINGS):
    return await save_routing(db, actor, body, settings)
