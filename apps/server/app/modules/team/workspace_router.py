from datetime import date
from fastapi import APIRouter, Query
from app.core.errors import problem
from app.http.dependencies import ADMIN, DB
from app.modules.team.workspace import report_view, work_view

router = APIRouter()


@router.get('/api/v1/team/workspace/{view}')
async def workspace(view: str, scope: str = 'current', kind: str = 'daily', period: str = 'this_week', start: date | None = None, end: date | None = None, q: str = Query('', max_length=200), status: str = '', members: str = 'active', member: str = '', offset: int = Query(0, ge=0), actor=ADMIN, db=DB):
    params = dict(period=period, start=start, end=end, q=q, status=status, members=members, member=member, offset=offset)
    if view == 'work':
        return await work_view(db, actor, scope=scope, **params)
    if view == 'reports':
        return await report_view(db, actor, kind=kind, **params)
    problem(404, '查看页面不存在')
