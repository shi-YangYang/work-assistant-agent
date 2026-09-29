from app.modules.deliverables.models import DeliverableLink, DeliverableRevision
from app.modules.work.models import WorkItem
from sqlalchemy import select


def summary(item, record):
    return {'id': item.id, 'revision': record.revision, 'latestRevision': item.revision, 'title': record.title, 'messageId': record.message_id, 'itemCount': len(record.items), 'files': [{'id': entry['id'], 'name': entry['name'], 'mimeType': entry['mimeType'], 'size': entry['size'], 'url': f"/api/v1/deliverables/{item.id}/files/{entry['id']}?revision={record.revision}"} for entry in record.files or []], 'updatedAt': record.created_at.isoformat()}


async def detail(db, actor, item, record):
    links = (await db.scalars(select(DeliverableLink).where(DeliverableLink.deliverable_id == item.id, DeliverableLink.owner_id == actor.id))).all()
    links = list({(link.item_id, link.work_id): link for link in links}.values())
    works = {w.id: w for w in (await db.scalars(select(WorkItem).where(WorkItem.id.in_([link.work_id for link in links]), WorkItem.owner_id == actor.id))).all()}
    return {**summary(item, record), 'body': record.body, 'items': record.items,
            'links': [{'itemId': link.item_id, 'workId': link.work_id, 'sourceRevision': link.source_revision, 'unavailable': not works.get(link.work_id) or works[link.work_id].deleted} for link in links]}


async def message_deliverables(db, actor, message):
    if actor.id != message.owner_id:
        return []
    from app.modules.deliverables.models import Deliverable
    from app.modules.deliverables.queries import available_revision
    rows = (await db.execute(select(Deliverable, DeliverableRevision).join(DeliverableRevision, DeliverableRevision.deliverable_id == Deliverable.id).where(DeliverableRevision.message_id == message.id, Deliverable.owner_id == actor.id).order_by(DeliverableRevision.step))).all()
    latest = {}
    for item, record in rows:
        if await available_revision(db, actor, item.id, record.revision) and (item.id not in latest or record.revision > latest[item.id]['revision']):
            latest[item.id] = summary(item, record)
    return list(latest.values())


async def delivery_summary(db, actor, message):
    """Fallback describes actual private version changes, never business success."""
    rows = (await db.scalars(select(DeliverableRevision).where(DeliverableRevision.message_id == message.id, DeliverableRevision.owner_id == actor.id).order_by(DeliverableRevision.step))).all()
    parts = []
    for record in rows:
        from app.modules.deliverables.queries import get_deliverable
        await get_deliverable(db, actor, record.deliverable_id, record.revision)
        previous = await db.scalar(select(DeliverableRevision).where(DeliverableRevision.deliverable_id == record.deliverable_id, DeliverableRevision.revision == record.revision - 1))
        if not previous:
            parts.append(f'已整理《{record.title}》' + (f'，包含 {len(record.items)} 个条目。' if record.items else '。'))
            continue
        old = {item['id']: item for item in previous.items}
        changed = [f'「{item["title"]}」' for item in record.items if old.get(item['id']) != item]
        notes = []
        if changed:
            notes.append('调整了' + '、'.join(changed[:5]) + ('等条目' if len(changed) > 5 else ''))
        if set(old) - {item['id'] for item in record.items}:
            notes.append('移除了不再保留的条目')
        if [item['id'] for item in previous.items] != [item['id'] for item in record.items] and set(old) == {item['id'] for item in record.items}:
            notes.append('调整了条目顺序')
        if record.body != previous.body:
            notes.append('更新了正文')
        if record.title != previous.title:
            notes.append('更新了标题')
        parts.append(f'《{record.title}》已更新为第 {record.revision} 版' + ('：' + '；'.join(notes) if notes else '') + '。')
    return '\n\n'.join(parts)
