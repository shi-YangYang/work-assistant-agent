import json
from paa_server.modules.reports.periods import period_bounds
from paa_server.modules.work.models import WorkItem, WorkRevision
from paa_server.security.access import require as business_require, valid as business_valid
from sqlalchemy import select


async def sources_for(db, report, actor, identifiers):
    start, end = period_bounds(report)
    sources = (await db.scalars(select(WorkRevision).join(WorkItem, WorkItem.id == WorkRevision.work_id).where(WorkRevision.id.in_(identifiers), WorkRevision.company_id == actor.company_id, WorkRevision.owner_id == actor.id, WorkItem.deleted.is_(False), WorkRevision.created_at >= start, WorkRevision.created_at < end, WorkRevision.access['team'].as_boolean().is_not(True)).order_by(WorkRevision.created_at, WorkRevision.id))).all()
    if len(sources) != len(set(identifiers)):
        raise ValueError('报告来源已变化，请根据有效工作重新生成')
    for source in sources:
        await business_require(db, actor, source.access)
    return sources


async def report_inputs(db, report):
    start, end = period_bounds(report)
    revisions = list((await db.scalars(select(WorkRevision).join(WorkItem, WorkItem.id == WorkRevision.work_id).where(WorkItem.deleted.is_(False), WorkRevision.owner_id == report.owner_id, WorkRevision.company_id == report.company_id, WorkRevision.created_at >= start, WorkRevision.created_at < end, WorkRevision.access['team'].as_boolean().is_not(True)).order_by(WorkRevision.created_at, WorkRevision.id))).all())
    # Latest revision per work within the selected period, not today's rewritten state.
    latest = {r.work_id: r for r in revisions}
    return list(latest.values())


async def report_fact_basis(db, actor, report):
    """Bounded, immutable source revisions, never another member's private data."""
    rows = (await db.scalars(select(WorkRevision).where(WorkRevision.id.in_(report.source_ids), WorkRevision.company_id == actor.company_id, WorkRevision.owner_id == actor.id).order_by(WorkRevision.id).limit(31))).all()
    items, remaining = [], 6000
    for row in rows[:30]:
        if not await business_valid(db, actor, row.access, retained=True):
            continue
        item = {'id': row.id, 'content': row.content}
        size = len(json.dumps(item, ensure_ascii=False))
        if size > remaining:
            break
        items.append(item)
        remaining -= size
    return {'items': items, 'complete': len(items) == len(report.source_ids)}
