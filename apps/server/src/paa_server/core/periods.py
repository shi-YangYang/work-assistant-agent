from datetime import datetime, time, timedelta
from paa_server.core.errors import problem
from paa_server.db.base import now
from zoneinfo import ZoneInfo


def period_range(company, period='this_week', start=None, end=None, instant=None):
    zone = ZoneInfo(company.rules['timezone'])
    today = (instant or now()).astimezone(zone).date()
    if period == 'custom':
        if not start or not end or start > end:
            problem(422, '请选择有效的开始与结束日期')
    elif period == 'today':
        start = end = today
    elif period == 'this_week':
        start, end = today - timedelta(days=today.weekday()), today - timedelta(days=today.weekday()) + timedelta(days=6)
    elif period == 'this_month':
        start = today.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    else:
        problem(422, '日期范围无效')
    try:
        upper = datetime.combine(end + timedelta(days=1), time.min, zone)
    except (OverflowError, ValueError):
        problem(422, '结束日期超出可查询范围，请选择 9999-12-30 或之前的日期')
    return datetime.combine(start, time.min, zone), upper, {'period': period, 'start': start.isoformat(), 'end': end.isoformat(), 'timezone': zone.key}
