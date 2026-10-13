from .commands import create_work_command, edit_draft_command, process_drafts_command
from .queries import work_item_query
from fastapi import APIRouter, Header, Query
from app.core.schemas import Revision
from app.http.dependencies import AUTH, DB, SETTINGS
from app.modules.operations.mutations.writes import remove_record as writes_remove_record
from app.modules.work.schemas import Confirm, DraftEdit, Progress, WorkEdit, WorkCreate
from app.modules.work.serializers import work_dto
from app.modules.work.service import save_work as writes_save_work
from app.tasks.maintenance.cleanup import finish_deletion
from typing import Annotated

router = APIRouter()


@router.post('/api/v1/work-items', status_code=201)
async def create_work(body: WorkCreate, idempotency_key: Annotated[str | None, Header()] = None, actor=AUTH, db=DB, settings=SETTINGS):
    if body.body is not None or body.bodyEdits is not None or body.materials:
        from app.modules.work.records.record_commands import record_command
        return (await record_command(db, actor, None, body, idempotency_key, settings))['work']
    return await create_work_command(Progress.model_validate(body.model_dump(exclude={'body', 'bodyEdits', 'materials'})), idempotency_key, actor, db)


@router.get('/api/v1/work-items')
async def work_items(q: str = Query('', max_length=200), status: str = '', cursor: str | None = None, limit: int = Query(20, ge=1, le=20), actor=AUTH, db=DB):
    from app.modules.work.queries import work_page
    return await work_page(db, actor, actor.id, q, status, cursor, limit)


@router.get('/api/v1/work-items/{identifier}')
async def work_item(identifier: str, revision: int | None = Query(None, ge=1), actor=AUTH, db=DB):
    return await work_item_query(identifier, revision, actor, db)


@router.patch('/api/v1/progress-drafts/{identifier}')
async def edit_draft(identifier: str, body: DraftEdit, actor=AUTH, db=DB):
    return await edit_draft_command(identifier, body, actor, db)


@router.post('/api/v1/progress-drafts/{action}')
async def process_drafts(action: str, body: Confirm, idempotency_key: Annotated[str | None, Header()] = None, actor=AUTH, db=DB):
    return await process_drafts_command(action, body, idempotency_key, actor, db)


@router.post('/api/v1/work-items/{identifier}/progress')
async def edit_work(identifier: str, body: WorkEdit, actor=AUTH, db=DB):
    work = await writes_save_work(db, actor, body.model_dump(mode='json', exclude={'expectedRevision', 'sourceIds'}, exclude_unset=True), identifier=identifier, expected=body.expectedRevision, sources=body.sourceIds)
    return work_dto(work)


@router.delete('/api/v1/work-items/{identifier}')
async def delete_work(identifier: str, body: Revision, actor=AUTH, db=DB, settings=SETTINGS):
    item = await writes_remove_record(db, actor, 'work', identifier, body.expectedRevision)
    return await finish_deletion(db, item.owner_id, settings)


from app.modules.work.records.record_schemas import WorkPatch, UpdateCreate, UpdateEdit, UpdateDelete, MaterialRemove
from app.modules.work.records.record_commands import record_command, remove_material_command


@router.patch('/api/v1/work-items/{identifier}')
async def patch_record(identifier: str, body: WorkPatch, idempotency_key: Annotated[str | None, Header()] = None, actor=AUTH, db=DB, settings=SETTINGS):
    return await record_command(db, actor, identifier, body, idempotency_key, settings)


@router.get('/api/v1/work-items/{identifier}/updates')
async def work_updates(identifier: str, start: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=50), revision: int | None = Query(None, ge=1), actor=AUTH, db=DB):
    from app.modules.work.updates.service import update_page
    from app.modules.work.materials.queries import readable_work
    work = await readable_work(db, actor, identifier, revision=revision)
    return await update_page(db, work, start, limit, revision=revision)


@router.post('/api/v1/work-items/{identifier}/updates', status_code=201)
async def create_update(identifier: str, body: UpdateCreate, idempotency_key: Annotated[str | None, Header()] = None, actor=AUTH, db=DB, settings=SETTINGS):
    return await record_command(db, actor, identifier, body, idempotency_key, settings, kind='update_create')


@router.patch('/api/v1/work-items/{identifier}/updates/{update_id}')
async def edit_update(identifier: str, update_id: str, body: UpdateEdit, idempotency_key: Annotated[str | None, Header()] = None, actor=AUTH, db=DB, settings=SETTINGS):
    return await record_command(db, actor, identifier, body, idempotency_key, settings, kind='update_edit', update_id=update_id)


@router.delete('/api/v1/work-items/{identifier}/updates/{update_id}')
async def delete_update(identifier: str, update_id: str, body: UpdateDelete, idempotency_key: Annotated[str | None, Header()] = None, actor=AUTH, db=DB, settings=SETTINGS):
    return await record_command(db, actor, identifier, body, idempotency_key, settings, kind='update_delete', update_id=update_id)


@router.get('/api/v1/work-items/{identifier}/materials')
async def work_materials(identifier: str, start: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=50), revision: int | None = Query(None, ge=1), actor=AUTH, db=DB):
    from app.modules.work.materials.service import material_page
    from app.modules.work.materials.queries import readable_work, historical_materials
    work = await readable_work(db, actor, identifier, revision=revision)
    return await material_page(db, actor, work, start, limit, historical_ids=await historical_materials(db, work, revision) if revision else None, work_revision=revision)


@router.post('/api/v1/work-items/{identifier}/materials', status_code=201)
async def add_materials(identifier: str, body: WorkPatch, idempotency_key: Annotated[str | None, Header()] = None, actor=AUTH, db=DB, settings=SETTINGS):
    return await record_command(db, actor, identifier, body, idempotency_key, settings, kind='materials')


@router.delete('/api/v1/work-items/{identifier}/materials/{material_id}')
async def remove_material(identifier: str, material_id: str, body: MaterialRemove, idempotency_key: Annotated[str | None, Header()] = None, actor=AUTH, db=DB):
    return await remove_material_command(db, actor, identifier, material_id, body, idempotency_key)


@router.get('/api/v1/work-items/{identifier}/materials/{material_id}')
async def single_material(identifier: str, material_id: str, revision: int | None = Query(None, ge=1), actor=AUTH, db=DB):
    from sqlalchemy import select
    from app.core.errors import problem
    from app.modules.work.materials.queries import readable_work, historical_materials
    from app.modules.work.materials.service import material_dto
    from app.modules.work.models import WorkMaterial
    from app.modules.attachments.models import Attachment
    work = await readable_work(db, actor, identifier, revision=revision)
    if revision and material_id not in await historical_materials(db, work, revision):
        problem(404, '该版本不包含此材料')
    row = await db.scalar(select(WorkMaterial).where(WorkMaterial.id == material_id, WorkMaterial.work_id == work.id))
    attachment = await db.get(Attachment, row.attachment_id) if row else None
    if not row or not attachment or attachment.deleted or row.removed and revision is None:
        problem(404, '材料不存在或已移除')
    return material_dto(row, attachment, work_revision=revision)


@router.get('/api/v1/work-items/{identifier}/updates/{update_id}')
async def single_update(identifier: str, update_id: str, revision: int | None = Query(None, ge=1), actor=AUTH, db=DB):
    from sqlalchemy import select
    from app.core.errors import problem
    from app.modules.work.materials.queries import readable_work
    from app.modules.work.models import WorkUpdate, WorkUpdateRevision
    from app.modules.work.updates.service import update_dto
    work = await readable_work(db, actor, identifier, revision=revision)
    row = await db.scalar(select(WorkUpdate).where(WorkUpdate.id == update_id, WorkUpdate.work_id == work.id))
    if not row:
        problem(404, '进展不存在')
    if revision:
        snapshot = await db.scalar(select(WorkUpdateRevision).where(WorkUpdateRevision.update_id == row.id, WorkUpdateRevision.work_revision <= revision).order_by(WorkUpdateRevision.revision.desc()).limit(1))
        if not snapshot or snapshot.deleted:
            problem(404, '该版本中进展不存在')
        return {**update_dto(row), 'revision': snapshot.revision, 'text': snapshot.text, 'materialIds': snapshot.material_ids, 'origin': snapshot.origin, 'updatedAt': snapshot.created_at.isoformat(), 'workRevision': snapshot.work_revision, 'deleted': False}
    if row.deleted:
        problem(404, '进展已删除')
    return update_dto(row)
