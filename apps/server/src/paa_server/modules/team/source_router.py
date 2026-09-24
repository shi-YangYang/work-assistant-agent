from fastapi import APIRouter
from paa_server.core.errors import problem
from paa_server.http.dependencies import AUTH, DB
from paa_server.modules.messages.models import Message
from paa_server.modules.team.sources import source_dto as business_source_dto
from paa_server.modules.work.models import WorkItem
from paa_server.security.access import require as business_require
from paa_server.security.ownership import owned

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
