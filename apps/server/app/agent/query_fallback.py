"""Recover a useful read result without trusting discarded model prose."""
import json
import re

from sqlalchemy import select

from app.modules.work.models import WorkItem
from app.security.access import valid


def plain(value):
    # Database titles/content can contain Markdown; render them as plain labels.
    return re.sub(r'([\\`*_{}\[\]<>#+!|])', r'\\\1', str(value).replace('\n', ' '))


def latest_query(evidence):
    """Keep the final read's scope; join only its actual pagination chain."""
    reads = []
    for item in evidence:
        if item['tool'] not in ('find_work_items', 'get_work_item'):
            continue
        try:
            result = json.loads(item['result'])
        except (ValueError, TypeError):
            continue
        if not isinstance(result, dict) or 'error' in result:
            continue
        reads.append((item['tool'], result))
    if not reads:
        return [], True, ''
    tool, last = reads[-1]
    if tool == 'get_work_item':
        return [last], False, '本次读取的工作'
    pages = [last]
    cursor = last.get('cursor', '')
    for name, page in reversed(reads[:-1]):
        if not cursor:
            break
        if name == tool and page.get('filters') == last.get('filters') and page.get('nextCursor') == cursor:
            pages.insert(0, page)
            cursor = page.get('cursor', '')
    rows = [row for page in pages for row in page.get('items', [])]
    filters = last.get('filters', {})
    labels = {'in_progress': '进行中', 'blocked': '受阻', 'done': '已完成'}
    scope = '、'.join(filter(None, [labels.get(filters.get('status')), '关键词：' + plain(filters['query']) if filters.get('query') else '']))
    return rows, bool(cursor or last.get('nextCursor')), '本次查询' + (f'（{scope}）' if scope else '')


async def work_query_fallback(db, actor, context):
    versions = {}
    rows, partial, scope = latest_query(context.reply_evidence)
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get('id'), str) and isinstance(row.get('revision'), int):
            versions[row['id']] = row['revision']
    if not versions:
        return scope + '没有找到符合条件的工作。' if scope and not rows and not partial else ''
    # A retained checkpoint is not permission to reveal deleted, changed or
    # revoked data. Re-check ownership, access and the exact read version.
    records = list((await db.scalars(select(WorkItem).where(WorkItem.id.in_(versions), WorkItem.company_id == actor.company_id, WorkItem.owner_id == actor.id, WorkItem.deleted.is_(False)))).all())
    statuses = {'in_progress': '进行中', 'blocked': '受阻', 'done': '已完成'}
    lines = []
    by_id = {row.id: row for row in records}
    for identifier in versions:
        row = by_id.get(identifier)
        if row is None:
            continue
        if row.revision != versions[row.id] or context.read_versions.get(row.id) != row.revision or not await valid(db, actor, row.access, retained=True):
            continue
        detail = row.content
        label = f"- {plain(row.title)} · {statuses.get(detail.get('status'), '状态未知')}"
        if detail.get('blocker'):
            label += '；阻碍：' + plain(detail['blocker'])
        lines.append(label)
    if not lines:
        return ''
    suffix = '\n以上是本次已读取的部分结果。' if partial or len(lines) < len(versions) else ''
    return scope + '结果：\n' + '\n'.join(lines) + suffix
