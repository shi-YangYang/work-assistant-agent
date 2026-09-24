from datetime import date
from fastapi import APIRouter, Query
from paa_server.http.dependencies import ADMIN, DB

router = APIRouter()


@router.get('/api/v1/settings/model-usage')
async def model_usage(period: str = 'this_week', start: date | None = None, end: date | None = None, service: str = Query('', max_length=36), model: str = Query('', max_length=200), purpose: str = Query('', max_length=16), cursor: str | None = None, limit: int = Query(20, ge=1, le=20), actor=ADMIN, db=DB):
    from paa_server.modules.model_services.usage import usage_page
    return await usage_page(db, actor, period=period, start=start, end=end, service=service, model=model, purpose=purpose, cursor=cursor, limit=limit)
