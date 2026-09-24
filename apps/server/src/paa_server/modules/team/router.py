from datetime import date
from fastapi import APIRouter, Query
from paa_server.core.errors import problem
from paa_server.http.dependencies import ADMIN, DB
from paa_server.modules.members.serializers import member_dto
from paa_server.modules.members.service import visible_member
from paa_server.modules.messages.queries import list_messages
from paa_server.modules.reports.models import Report
from paa_server.modules.reports.queries import report_dtos
from sqlalchemy import select

router = APIRouter()


@router.get('/api/v1/team')
async def team(period: str = 'this_week', start: date | None = None, end: date | None = None, q: str = Query('', max_length=200), status: str = '', members: str = 'active', actor=ADMIN, db=DB):
    from paa_server.modules.team.metrics import team_data
    summary, _ = await team_data(db, actor, period=period, start=start, end=end, q=q, status=status, members=members)
    return summary


@router.get('/api/v1/team/details')
async def team_details(metric: str, period: str = 'this_week', start: date | None = None, end: date | None = None, q: str = Query('', max_length=200), status: str = '', members: str = 'active', cursor: str | None = None, limit: int = Query(20, ge=1, le=20), actor=ADMIN, db=DB):
    from paa_server.modules.team.metrics import team_data
    from paa_server.core.pagination import detail_page
    if metric not in ('messages', 'blocked', 'reports'):
        problem(422, '统计指标无效')
    summary, details = await team_data(db, actor, period=period, start=start, end=end, q=q, status=status, members=members)
    return {**detail_page(details[metric], cursor, limit), 'range': summary['range'], 'metrics': summary['metrics'], 'total': len(details[metric])}


@router.get('/api/v1/team/members/{identifier}/messages')
async def team_messages(identifier: str, cursor: str | None = None, limit: int = Query(50, ge=1, le=100), actor=ADMIN, db=DB):
    await visible_member(db, actor, identifier, employee_only=True)
    return await list_messages(db, actor, identifier, cursor, limit)


@router.get('/api/v1/team/members/{identifier}/work')
async def team_work(identifier: str, q: str = Query('', max_length=200), status: str = '', cursor: str | None = None, limit: int = Query(20, ge=1, le=20), actor=ADMIN, db=DB):
    from paa_server.modules.work.queries import work_page
    member = await visible_member(db, actor, identifier, employee_only=True)
    return {'member': member_dto(member), **await work_page(db, actor, identifier, q, status, cursor, limit)}


@router.get('/api/v1/team/members/{identifier}/reports')
async def team_reports(identifier: str, kind: str = 'daily', cursor: str | None = None, actor=ADMIN, db=DB):
    await visible_member(db, actor, identifier, employee_only=True)
    query = select(Report).where(Report.deleted.is_(False), Report.owner_id == identifier, Report.kind == kind, Report.published_revision > 0)
    if cursor:
        query = query.where(Report.period < cursor)
    rows = (await db.scalars(query.order_by(Report.period.desc()).limit(51))).all()
    return {'items': await report_dtos(db, rows[:50], actor), 'nextCursor': rows[49].period if len(rows) > 50 else None}
