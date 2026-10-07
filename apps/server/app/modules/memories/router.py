from fastapi import APIRouter, Query
from app.http.dependencies import AUTH, READ_AUTH, DB
from .schemas import MemorySettings, MemoryDocument
from . import service

router = APIRouter(prefix='/api/v1/assistant/memory', tags=['memory'])


@router.get('')
async def get_memory(actor=READ_AUTH, db=DB):
    return service.dto(await service.read(db, actor))


@router.patch('/settings')
async def memory_settings(body: MemorySettings, actor=AUTH, db=DB):
    return await service.settings(db, actor, body.expectedRevision, body.enabled)


@router.put('/document')
async def memory_document(body: MemoryDocument, actor=AUTH, db=DB):
    return await service.save_document(db, actor, body.expectedRevision, body.markdown)


@router.delete('/document')
async def clear_memory(expectedRevision: int = Query(ge=0), actor=AUTH, db=DB):
    return await service.save_document(db, actor, expectedRevision, '')
