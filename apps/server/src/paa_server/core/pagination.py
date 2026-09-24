import base64
import json
from datetime import datetime
from paa_server.core.errors import problem


def cursor_encode(instant, identifier):
    return base64.urlsafe_b64encode(json.dumps([instant.isoformat(), identifier]).encode()).decode().rstrip('=')


def cursor_decode(value):
    try:
        if len(value) > 200:
            raise ValueError()
        stamp, identifier = json.loads(base64.urlsafe_b64decode(value + '=' * (-len(value) % 4)))
        instant = datetime.fromisoformat(stamp)
        if not instant.tzinfo or not isinstance(identifier, str) or len(identifier) > 36:
            raise ValueError()
        return instant, identifier
    except (ValueError, TypeError, UnicodeError):
        problem(422, '分页位置无效，请重新打开列表')


def detail_page(rows, cursor=None, limit=20):
    rows = sorted(rows, key=lambda row: (datetime.fromisoformat(row['at']), row['id']), reverse=True)
    if cursor:
        boundary = cursor_decode(cursor)
        rows = [row for row in rows if (datetime.fromisoformat(row['at']), row['id']) < boundary]
    return {'items': rows[:limit], 'nextCursor': cursor_encode(datetime.fromisoformat(rows[limit - 1]['at']), rows[limit - 1]['id']) if len(rows) > limit else None}
