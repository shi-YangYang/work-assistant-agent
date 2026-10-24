"""Shared controlled fixtures extracted from test_team_workspace."""
from datetime import datetime, timedelta, timezone
from app.modules.reports.models import Report, ReportRevision


DAY = datetime(2026, 9, 12, 6, tzinfo=timezone.utc)


RANGE = {'period': 'custom', 'start': '2026-09-12', 'end': '2026-09-12'}


async def report(db, actor, period, *, published=True):
    public = {'completed': '已提交内容', 'ongoing': '', 'blockers': '', 'next': ''}
    from datetime import date, timedelta
    start = date.fromisoformat(period)
    start -= timedelta(days=start.weekday())
    period = start.isoformat()
    row = Report(company_id=actor.company_id, owner_id=actor.id, kind='weekly', period=period, period_end=(start + timedelta(days=6)).isoformat(), timezone='Asia/Shanghai', content={'completed': '不能泄露的后续草稿'}, revision=2, published_revision=1 if published else 0)
    db.add(row)
    await db.flush()
    if published:
        db.add(ReportRevision(company_id=row.company_id, owner_id=row.owner_id, report_id=row.id, revision=1, content=public, source_ids=[], created_at=DAY + timedelta(days=5)))
    return row
