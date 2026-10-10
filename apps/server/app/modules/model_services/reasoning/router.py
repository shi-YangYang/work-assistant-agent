from fastapi import APIRouter
from .schemas import UpdateReasoning
from app.http.dependencies import AUTH, DB
from .settings import read_settings, update_settings

router = APIRouter()


@router.get('/api/v1/assistant/reasoning-settings')
async def read(actor=AUTH, db=DB):
    return await read_settings(db, actor)


@router.patch('/api/v1/assistant/reasoning-settings')
async def update(body: UpdateReasoning, actor=AUTH, db=DB):
    return await update_settings(db, actor, body)
