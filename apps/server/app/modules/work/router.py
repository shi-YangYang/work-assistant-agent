from .commands import create_work_command, edit_draft_command, process_drafts_command
from .queries import work_item_query
from fastapi import APIRouter, Header, Query
from app.core.schemas import Revision
from app.http.dependencies import AUTH, DB, SETTINGS
from app.modules.operations.writes import remove_record as writes_remove_record
from app.modules.work.schemas import Confirm, DraftEdit, Progress, WorkEdit
from app.modules.work.serializers import work_dto
from app.modules.work.service import save_work as writes_save_work
from app.tasks.cleanup import finish_deletion
from typing import Annotated

router = APIRouter()


@router.post('/api/v1/work-items', status_code=201)
async def create_work(body: Progress, idempotency_key: Annotated[str | None, Header()] = None, actor=AUTH, db=DB):
    return await create_work_command(body, idempotency_key, actor, db)


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
