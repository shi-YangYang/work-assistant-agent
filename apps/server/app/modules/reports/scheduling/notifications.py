from app.modules.reports.models import ReportNotification, ReportObligation
from sqlalchemy import func, select


def notification_query(actor):
    return select(ReportNotification, ReportObligation).join(ReportObligation, ReportObligation.id == ReportNotification.obligation_id).where(
        ReportNotification.company_id == actor.company_id, ReportNotification.owner_id == actor.id,
        ReportObligation.state == 'pending')


async def unread_count(db, actor):
    if actor.role != 'employee':
        return 0
    return await db.scalar(select(func.count()).select_from(
        notification_query(actor).where(ReportNotification.read_at.is_(None)).subquery())) or 0
