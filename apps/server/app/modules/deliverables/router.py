from fastapi import APIRouter, Query, Request
from app.http.dependencies import AUTH, DB
from app.modules.deliverables.queries import get_deliverable, conversation_deliverables, available_revision
from app.modules.deliverables.serializers import summary, detail
from app.security.access import valid

router = APIRouter()


@router.get('/api/v1/deliverables')
async def list_deliverables(conversationId: str, offset: int = Query(0, ge=0), actor=AUTH, db=DB):
    rows = await conversation_deliverables(db, actor, conversationId, offset)
    items = []
    for row in rows[:20]:
        if await valid(db, actor, row.access):
            record = await available_revision(db, actor, row.id)
            if record:
                items.append(summary(row, record))
    return {'items': items, 'nextOffset': offset + 20 if len(rows) > 20 else None}


@router.get('/api/v1/deliverables/{identifier}')
async def read_deliverable(identifier: str, revision: int | None = Query(None, ge=1), actor=AUTH, db=DB):
    item, record = await get_deliverable(db, actor, identifier, revision)
    return await detail(db, actor, item, record)


@router.get('/api/v1/deliverables/{identifier}/files/{file_id}')
async def download_file(identifier: str, file_id: str, request: Request, revision: int = Query(..., ge=1), actor=AUTH, db=DB):
    from fastapi.responses import FileResponse
    from app.core.errors import problem
    from app.modules.executions.files import file_path
    from app.modules.executions.sources import check_sources
    _, record = await get_deliverable(db, actor, identifier, revision)
    item = next((entry for entry in record.files if entry['id'] == file_id), None)
    if not item:
        problem(404, '成果文件不存在')
    await check_sources(db, actor, item.get('sources', []))
    path = file_path(request.app.state.settings, item['storageKey'])
    if not path.is_file() or path.is_symlink():
        problem(404, '成果文件已不可用')
    return FileResponse(path, media_type=item['mimeType'], filename=item['name'],
                        content_disposition_type='inline' if item['mimeType'] == 'image/png' else 'attachment',
                        headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'none'; sandbox"})
