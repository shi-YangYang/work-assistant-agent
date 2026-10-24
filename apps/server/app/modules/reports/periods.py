from datetime import date, datetime, time, timedelta, timezone
from app.core.errors import problem
from zoneinfo import ZoneInfo


def period(kind, value: date):
    require_weekly(kind)
    try:
        start = value - timedelta(days=value.weekday())
        end = start + timedelta(days=6)
        end + timedelta(days=1)
    except OverflowError:
        problem(422, '报告日期超出可生成范围，请选择更早的日期')
    return start, end


def period_bounds(report):
    zone = ZoneInfo(report.timezone)
    start = datetime.combine(date.fromisoformat(report.period), time.min, zone)
    end = datetime.combine(date.fromisoformat(report.period_end) + timedelta(days=1), time.min, zone)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def require_weekly(kind):
    if kind != 'weekly':
        problem(410 if kind == 'daily' else 422, '正式日报已取消，仅支持周报', 'report_kind_retired')
