import json
from app.modules.reports.periods import period_bounds
from app.modules.work.models import WorkItem, WorkRevision, WorkUpdate, WorkUpdateRevision
from app.security.access import require as business_require, valid as business_valid
from sqlalchemy import select


async def sources_for(db, report, actor, identifiers):
    start, end = period_bounds(report)
    sources = (await db.scalars(select(WorkRevision).join(WorkItem, WorkItem.id == WorkRevision.work_id).where(WorkRevision.id.in_(identifiers), WorkRevision.company_id == actor.company_id, WorkRevision.owner_id == actor.id, WorkItem.deleted.is_(False), ((WorkRevision.created_at >= start) & (WorkRevision.created_at < end)) | WorkRevision.id.in_(select(WorkRevision.id).join(WorkUpdate, (WorkUpdate.work_id == WorkRevision.work_id) & (WorkUpdate.work_revision == WorkRevision.revision)).where(WorkUpdate.deleted.is_(False), WorkUpdate.created_at >= start, WorkUpdate.created_at < end)), WorkRevision.access['team'].as_boolean().is_not(True)).order_by(WorkRevision.created_at, WorkRevision.id))).all()
    if len(sources) != len(set(identifiers)):
        raise ValueError('报告来源已变化，请根据有效工作重新生成')
    for source in sources:
        entry = await db.scalar(select(WorkUpdate).join(WorkUpdateRevision, WorkUpdateRevision.update_id == WorkUpdate.id).where(WorkUpdate.work_id == source.work_id, WorkUpdateRevision.work_revision == source.revision))
        if entry and (entry.deleted or entry.work_revision != source.revision):
            raise ValueError('报告来源已变化，请根据有效工作重新生成')
        await business_require(db, actor, source.access)
        await business_require(db, actor, (await db.get(WorkItem, source.work_id)).access, retained=True)
    return sources


async def report_inputs(db, report):
    start, end = period_bounds(report)
    revisions = list((await db.scalars(select(WorkRevision).join(WorkItem, WorkItem.id == WorkRevision.work_id).where(WorkItem.deleted.is_(False), WorkRevision.owner_id == report.owner_id, WorkRevision.company_id == report.company_id, WorkRevision.created_at >= start, WorkRevision.created_at < end, WorkRevision.access['team'].as_boolean().is_not(True)).order_by(WorkRevision.created_at, WorkRevision.id))).all())
    # Every progress entry, including migrated and legacy-API entries, points at
    # its current immutable work snapshot. Metadata is not an entry identity.
    updates = list((await db.scalars(select(WorkRevision).join(WorkUpdate, (WorkUpdate.work_id == WorkRevision.work_id) & (WorkUpdate.work_revision == WorkRevision.revision)).join(WorkItem, WorkItem.id == WorkUpdate.work_id).where(WorkItem.deleted.is_(False), WorkUpdate.deleted.is_(False), WorkUpdate.owner_id == report.owner_id, WorkUpdate.company_id == report.company_id, WorkUpdate.created_at >= start, WorkUpdate.created_at < end, WorkRevision.access['team'].as_boolean().is_not(True)).order_by(WorkUpdate.created_at, WorkUpdate.id))).all())
    # A legacy summary can also occur in later property-only snapshots. Match
    # the original entry revision/text, including tombstones and old corrections,
    # so neither those inherited summaries nor removed entries are counted again.
    represented = select(WorkUpdateRevision.id).join(WorkUpdate, WorkUpdate.id == WorkUpdateRevision.update_id).where(WorkUpdate.work_id == WorkRevision.work_id, WorkUpdateRevision.work_revision <= WorkRevision.revision, WorkUpdateRevision.text == WorkRevision.content['summary'].astext).exists()
    legacy_ids = set((await db.scalars(select(WorkRevision.id).where(WorkRevision.id.in_([r.id for r in revisions]), ~represented))).all())
    legacy = {r.work_id: r for r in revisions if not r.content.get('_changeKind') and r.id in legacy_ids}
    properties = {r.work_id: r for r in revisions if r.content.get('_changeKind') == 'properties'}
    return [*legacy.values(), *properties.values(), *updates]


async def report_fact_basis(db, actor, report, *, full=False):
    """Bounded, immutable source revisions, never another member's private data."""
    statement = select(WorkRevision).where(WorkRevision.id.in_(report.source_ids), WorkRevision.company_id == actor.company_id, WorkRevision.owner_id == actor.id).order_by(WorkRevision.id)
    rows = (await db.scalars(statement if full else statement.limit(31))).all()
    items, included, budget = [], [], None if full else 6000
    for row in (rows if full else rows[:30]):
        if not await business_valid(db, actor, row.access, retained=True):
            continue
        item = {'id': row.id, 'content': report_source_content(row)}
        size = len(json.dumps({'items': [*items, item], 'workContextsForPlansOnly': report_plan_contexts([*included, row])}, ensure_ascii=False))
        if budget is not None and size > budget:
            break
        items.append(item)
        included.append(row)
    return {'items': items, 'workContextsForPlansOnly': report_plan_contexts(included), 'complete': len(items) == len(report.source_ids)}


def report_plan_contexts(revisions):
    """Plans come from the same immutable source snapshots, never today's work."""
    latest = {}
    for revision in revisions:
        previous = latest.get(revision.work_id)
        if previous is None or revision.revision > previous.revision:
            latest[revision.work_id] = revision
    from app.modules.work.content.document import plain_text
    return [{'sourceId': row.id, 'workId': row.work_id, 'title': row.content.get('title', ''), 'bodyText': plain_text(row.content['body']) if row.content.get('body') is not None else row.content.get('bodyText', '')}
            for row in latest.values() if row.content.get('body') or row.content.get('bodyText')]


def report_source_content(revision):
    content = revision.content
    result = {key: content.get(key) for key in ('title', 'summary', 'status', 'dueDate', 'blocker', 'nextStep')}
    if content.get('_updateId'):
        result['summary'] = content.get('_updateText', '')
        result['updateId'] = content['_updateId']
    if content.get('_changeKind') == 'properties':
        result['summary'] = ''
        result['factType'] = 'attribute_change'
    return result
