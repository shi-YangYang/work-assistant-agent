"""Web session deadlines; the original login time never moves."""
from datetime import timedelta

IDLE_LIFETIME = timedelta(days=7)
ABSOLUTE_LIFETIME = timedelta(days=30)
RENEWAL_INTERVAL = timedelta(minutes=30)
DESKTOP_LIFETIME = timedelta(hours=8)


def deadline(created_at, instant):
    return min(instant + IDLE_LIFETIME, created_at + ABSOLUTE_LIFETIME)


def renewal_due(created_at, expires_at, instant):
    absolute = created_at + ABSOLUTE_LIFETIME
    if instant >= min(expires_at, absolute):
        return False
    target = deadline(created_at, instant)
    # Legacy eight-hour sessions naturally qualify on their first valid access.
    # One final write may fill the absolute cap before the normal interval.
    return target > expires_at and (target - expires_at >= RENEWAL_INTERVAL or target == absolute)
