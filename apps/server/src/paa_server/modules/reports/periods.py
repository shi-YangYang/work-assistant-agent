from datetime import date, datetime, time, timedelta, timezone
from paa_server.core.errors import problem
from zoneinfo import ZoneInfo


def period(kind, value: date):
    try:
        start = value if kind == 'daily' else value - timedelta(days=value.weekday())
        end = start if kind == 'daily' else start + timedelta(days=6)
        end + timedelta(days=1)
    except OverflowError:
        problem(422, '报告日期超出可生成范围，请选择更早的日期')
    return start, end


def period_bounds(report):
    zone = ZoneInfo(report.timezone)
    start = datetime.combine(date.fromisoformat(report.period), time.min, zone)
    end = datetime.combine(date.fromisoformat(report.period_end) + timedelta(days=1), time.min, zone)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)
