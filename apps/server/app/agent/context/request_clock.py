"""Deterministic local calendar facts; no invented date for weekday templates."""
from datetime import timedelta
from zoneinfo import ZoneInfo


def instruction(clock, timezone):
    local = clock.astimezone(ZoneInfo(timezone))
    monday = local.date() - timedelta(days=local.weekday())
    week = '；'.join(f"周{day}={(monday + timedelta(days=index)).isoformat()}" for index, day in enumerate('一二三四五六日'))
    return (f"当前请求时间：{local.isoformat()}（周{'一二三四五六日'[local.weekday()]}）；公司时区：{timezone}。本周日历：{week}。"
            '用户明确历史/未来日期优先，不改成当前日期。相对日期以此换算并写具体年月日；仅要求某星期的示例/模板且未指定实际日期时，保留星期即可，不把当前日期强加为该星期。')
