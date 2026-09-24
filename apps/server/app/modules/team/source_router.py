from fastapi import APIRouter
from app.core.errors import problem
from app.http.dependencies import AUTH, DB
from app.modules.messages.models import Message
from app.modules.team.sources import source_dto as business_source_dto
from app.modules.work.models import WorkItem
from app.security.access import require as business_require
from app.security.ownership import owned

router = APIRouter()


@router.get('/api/v1/business-sources/{message_id}/{token}')
async def business_source(message_id: str, token: str, actor=AUTH, db=DB):
    item = await owned(db, Message, message_id, actor)
    await business_require(db, actor, item.access)
    evidence = item.access.get('reads', {}).get(token)
    if not evidence:
        problem(404, '来源不存在或无权查看')
    return await business_source_dto(db, actor, evidence, token)


@router.get('/api/v1/work-items/{identifier}/business-sources/{token}')
async def work_business_source(identifier: str, token: str, actor=AUTH, db=DB):
    item = await owned(db, WorkItem, identifier, actor)
    await business_require(db, actor, item.access, retained=True)
    link = next((link for link in item.business_links if link['token'] == token), None)
    if not link:
        problem(404, '来源不存在或无权查看')
    return await business_source_dto(db, actor, link['evidence'], token)
