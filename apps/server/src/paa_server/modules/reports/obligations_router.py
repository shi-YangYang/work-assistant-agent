from .commands import prepare_obligation_command
from datetime import date
from fastapi import APIRouter, Header, Query
from paa_server.core.errors import problem
from paa_server.db.base import now
from paa_server.http.dependencies import ADMIN, AUTH, DB
from paa_server.modules.members.models import Company
from paa_server.modules.reports.models import ReportNotification, ReportObligation
from paa_server.modules.reports.schedule import obligation_dto as reporting_obligation_dto, obligation_page as reporting_obligation_page
from paa_server.security.ownership import owned
from sqlalchemy import func, select
from typing import Annotated

router = APIRouter()


@router.get('/api/v1/report-obligations')
async def report_obligations(kind: str = 'daily', status: str = '', period: date | None = None, cursor: int = Query(0, ge=0), actor=AUTH, db=DB):
    if actor.role != 'employee':
        problem(403, '管理员没有个人汇报待办')
    return await reporting_obligation_page(db, actor, kind=kind, status=status, selected_period=period, cursor=cursor)


@router.get('/api/v1/team/report-obligations')
async def team_report_obligations(kind: str = 'daily', status: str = '', period: date | None = None, cursor: int = Query(0, ge=0), actor=ADMIN, db=DB):
    if period is None:
        from zoneinfo import ZoneInfo
        company = await db.get(Company, actor.company_id)
        period = now().astimezone(ZoneInfo(company.rules['timezone'])).date()
    return await reporting_obligation_page(db, actor, kind=kind, status=status, selected_period=period, cursor=cursor, team=True)


@router.post('/api/v1/report-obligations/{identifier}/prepare')
async def prepare_obligation(identifier: str, idempotency_key: Annotated[str | None, Header()] = None, actor=AUTH, db=DB):
    return await prepare_obligation_command(identifier, idempotency_key, actor, db)


@router.get('/api/v1/notifications')
async def notifications(cursor: int = Query(0, ge=0), actor=AUTH, db=DB):
    if actor.role != 'employee':
        return {'items': [], 'nextCursor': None, 'unread': 0}
    base = select(ReportNotification, ReportObligation).join(ReportObligation, ReportObligation.id == ReportNotification.obligation_id).where(ReportNotification.company_id == actor.company_id, ReportNotification.owner_id == actor.id, ReportObligation.state == 'pending')
    unread = await db.scalar(select(func.count()).select_from(base.where(ReportNotification.read_at.is_(None)).subquery()))
    rows = (await db.execute(base.order_by(ReportNotification.updated_at.desc(), ReportNotification.id).offset(cursor).limit(21))).all()
    return {'items': [{'id': notice.id, 'stage': notice.stage, 'read': notice.read_at is not None, 'updatedAt': notice.updated_at.isoformat(), 'obligation': reporting_obligation_dto(obligation, now(), own=True)} for notice, obligation in rows[:20]], 'nextCursor': str(cursor + 20) if len(rows) > 20 else None, 'unread': unread}


@router.post('/api/v1/notifications/{identifier}/read')
async def read_notification(identifier: str, actor=AUTH, db=DB):
    notice = await owned(db, ReportNotification, identifier, actor, lock=True)
    notice.read_at = notice.read_at or now()
    return {'ok': True}
