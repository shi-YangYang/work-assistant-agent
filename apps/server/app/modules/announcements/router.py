from typing import Annotated, Literal
from fastapi import APIRouter, Header, Query
from app.http.dependencies import ADMIN, AUTH, DB, READ_AUTH
from app.modules.announcements import service
from app.modules.announcements.schemas import AnnouncementCreate, AnnouncementPatch, AnnouncementVersion

router = APIRouter(prefix='/api/v1/announcements')


@router.get('')
async def list_announcements(state: Literal['published', 'withdrawn'] = 'published', cursor: int = Query(0, ge=0, le=1000000), actor=READ_AUTH, db=DB):
    return await service.page(db, actor, state, cursor)


@router.get('/{identifier}')
async def get_announcement(identifier: str, management: bool = False, actor=READ_AUTH, db=DB):
    return await service.detail(db, actor, identifier, management)


@router.post('', status_code=201)
async def publish_announcement(body: AnnouncementCreate, idempotency_key: Annotated[str | None, Header(max_length=100)] = None, actor=ADMIN, db=DB):
    return await service.create(db, actor, body, idempotency_key)


@router.patch('/{identifier}')
async def edit_announcement(identifier: str, body: AnnouncementPatch, actor=ADMIN, db=DB):
    return await service.update(db, actor, identifier, body)


@router.delete('/{identifier}')
async def delete_announcement(identifier: str, body: AnnouncementVersion, idempotency_key: Annotated[str | None, Header(max_length=100)] = None, actor=ADMIN, db=DB):
    return await service.delete_announcement(db, actor, identifier, body, idempotency_key)


@router.post('/{identifier}/read')
async def read_announcement(identifier: str, body: AnnouncementVersion, actor=AUTH, db=DB):
    return await service.mark_read(db, actor, identifier, body)
