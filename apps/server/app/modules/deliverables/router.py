from fastapi import APIRouter, Query
from app.http.dependencies import AUTH, DB
from app.modules.deliverables.queries import get_deliverable, conversation_deliverables
from app.modules.deliverables.serializers import summary, detail
from app.security.access import valid

router = APIRouter()


@router.get('/api/v1/deliverables')
async def list_deliverables(conversationId: str, offset: int = Query(0, ge=0), actor=AUTH, db=DB):
    rows = await conversation_deliverables(db, actor, conversationId, offset)
    items = []
    for row in rows[:20]:
        if await valid(db, actor, row.access):
            _, record = await get_deliverable(db, actor, row.id)
            items.append(summary(row, record))
    return {'items': items, 'nextOffset': offset + 20 if len(rows) > 20 else None}


@router.get('/api/v1/deliverables/{identifier}')
async def read_deliverable(identifier: str, revision: int | None = Query(None, ge=1), actor=AUTH, db=DB):
    item, record = await get_deliverable(db, actor, identifier, revision)
    return await detail(db, actor, item, record)
