from fastapi import APIRouter, Header
from app.core.schemas import Revision
from app.http.dependencies import AUTH, DB
from app.modules.interactions.schemas import AnswerRequest
from app.modules.interactions import service
from app.modules.interactions.queries import conversation_rows
from app.modules.interactions.serializers import interaction_dto

router = APIRouter()


@router.get('/api/v1/conversations/{identifier}/interactions')
async def interactions(identifier: str, actor=AUTH, db=DB):
    rows = await conversation_rows(db, actor, identifier)
    return {'items': [await interaction_dto(db, actor, row) for row in rows]}


@router.post('/api/v1/interactions/{identifier}/answer')
async def answer(identifier: str, body: AnswerRequest, idempotency_key: str = Header(alias='Idempotency-Key'), actor=AUTH, db=DB):
    return await service.answer(db, actor, identifier, body, idempotency_key)


@router.post('/api/v1/interactions/{identifier}/cancel')
async def cancel(identifier: str, body: Revision, actor=AUTH, db=DB):
    return await service.cancel(db, actor, identifier, body.expectedRevision)
