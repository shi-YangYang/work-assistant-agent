import json
from app.modules.reports.periods import period_bounds
from app.modules.work.models import WorkItem, WorkRevision, WorkUpdate, WorkUpdateRevision
from app.security.access import require as business_require
from sqlalchemy import select


async def sources_for(db, report, actor, identifiers):
    start, end = period_bounds(report)
    sources = list((await db.scalars(select(WorkRevision).join(WorkItem, WorkItem.id == WorkRevision.work_id).where(
        WorkRevision.id.in_(identifiers), WorkRevision.company_id == actor.company_id,
        WorkRevision.owner_id == actor.id, WorkItem.deleted.is_(False), WorkRevision.created_at < end,
        (WorkRevision.created_at >= start) | WorkRevision.id.in_(select(WorkRevision.id).join(
            WorkUpdate, (WorkUpdate.work_id == WorkRevision.work_id) & (WorkUpdate.work_revision == WorkRevision.revision)).where(
                WorkUpdate.deleted.is_(False), WorkUpdate.created_at >= start, WorkUpdate.created_at < end)),
        WorkRevision.access['team'].as_boolean().is_not(True)).order_by(WorkRevision.created_at, WorkRevision.revision, WorkRevision.id))).all())
    if len(sources) != len(set(identifiers)):
        raise ValueError('报告来源已变化，请根据有效工作重新生成')
    for source in sources:
        await business_require(db, actor, source.access)
        await business_require(db, actor, (await db.get(WorkItem, source.work_id)).access, retained=True)
    return sources


async def report_inputs(db, report):
    start, end = period_bounds(report)
    revisions = list((await db.scalars(select(WorkRevision).join(WorkItem, WorkItem.id == WorkRevision.work_id).where(
        WorkItem.deleted.is_(False), WorkRevision.owner_id == report.owner_id, WorkRevision.company_id == report.company_id,
        WorkRevision.created_at >= start, WorkRevision.created_at < end,
        WorkRevision.access['team'].as_boolean().is_not(True)).order_by(WorkRevision.created_at, WorkRevision.revision, WorkRevision.id))).all())
    updates = list((await db.scalars(select(WorkRevision).join(WorkUpdate,
        (WorkUpdate.work_id == WorkRevision.work_id) & (WorkUpdate.work_revision == WorkRevision.revision)).join(
            WorkItem, WorkItem.id == WorkUpdate.work_id).where(
                WorkItem.deleted.is_(False), WorkUpdate.deleted.is_(False), WorkUpdate.owner_id == report.owner_id,
                WorkUpdate.company_id == report.company_id, WorkRevision.created_at < end,
                ((WorkUpdate.created_at >= start) & (WorkUpdate.created_at < end)) | (WorkRevision.created_at >= start),
                WorkRevision.access['team'].as_boolean().is_not(True)).order_by(WorkUpdate.created_at, WorkUpdate.id))).all())
    latest, states, previous = {}, [], {}
    for row in sorted(revisions, key=lambda row: (row.work_id, row.revision)):
        latest[row.work_id] = row
        status = row.content.get('status')
        if row.work_id not in previous or previous[row.work_id] != status:
            states.append(row)
        previous[row.work_id] = status
    # Keep state transitions (including reopening) and every valid progress
    # entry. Ordinary body edits need only the last in-period immutable body.
    selected = {row.id: row for row in [*states, *latest.values(), *updates]}
    return sorted(selected.values(), key=lambda row: (row.created_at, row.revision, row.id))


def report_source_content(revision):
    content = revision.content
    result = {**{key: content.get(key) for key in ('title', 'status', 'dueDate', 'blocker', 'nextStep')},
            'sourceId': revision.id, 'workId': revision.work_id, 'revision': revision.revision,
            'recordedAt': revision.created_at.isoformat(), 'changeKind': content.get('_changeKind', 'legacy')}
    result['summary'] = content.get('_updateText', content.get('summary', ''))
    if content.get('_changeKind') == 'properties':
        result.update(summary='', factType='attribute_change')
    return result


async def source_payload(db, revisions, *, historical=False):
    """Separate immutable work states from current, non-deleted progress entries."""
    if not revisions:
        return []
    work_ids = {row.work_id for row in revisions}
    updates = list((await db.scalars(select(WorkUpdate).where(WorkUpdate.work_id.in_(work_ids)))).all())
    histories = list((await db.scalars(select(WorkUpdateRevision).where(
        WorkUpdateRevision.update_id.in_([row.id for row in updates])))).all())
    represented = {(row.work_id, history.text) for row in updates for history in histories if history.update_id == row.id}
    active = {(row.work_id, row.work_revision): row for row in updates if not row.deleted}
    latest = {}
    for row in revisions:
        if row.work_id not in latest or latest[row.work_id].revision < row.revision:
            latest[row.work_id] = row
    from app.modules.work.content.document import plain_text
    result = []
    for row in revisions:
        content = report_source_content(row)
        current = active.get((row.work_id, row.revision))
        content['summary'] = content['summary'] if historical else current.text if current else (
            row.content.get('summary', '') if not row.content.get('_changeKind')
            and (row.work_id, row.content.get('summary', '')) not in represented else '')
        if current and not historical:
            content.update(updateId=current.id, updateRevision=current.revision,
                           progressCreatedAt=current.created_at.isoformat())
        content['isLatestWorkState'] = latest[row.work_id].id == row.id
        if content['isLatestWorkState']:
            body = row.content.get('body')
            content['body'] = body
            content['bodyText'] = plain_text(body) if body is not None else row.content.get('bodyText', '')
        result.append({'id': row.id, 'content': content})
    return result


async def report_fact_basis(db, actor, report, *, full=False):
    """Read the report's fixed snapshots with live ownership/source protection."""
    from fastapi import HTTPException
    from app.modules.reports.models import ReportRevision
    historical = isinstance(report, ReportRevision)
    try:
        rows = list((await db.scalars(select(WorkRevision).where(
            WorkRevision.id.in_(report.source_ids), WorkRevision.owner_id == actor.id,
            WorkRevision.company_id == actor.company_id).order_by(WorkRevision.created_at, WorkRevision.revision, WorkRevision.id))).all()) if historical else await sources_for(db, report, actor, report.source_ids)
        if historical:
            for row in rows:
                await business_require(db, actor, row.access, retained=True)
    except (ValueError, HTTPException):
        return {'items': [], 'complete': False}
    payload = await source_payload(db, rows, historical=historical)
    items, size = [], 0
    for item in payload:
        size += len(json.dumps(item, ensure_ascii=False))
        if not full and (len(items) >= 30 or size > 6000):
            break
        items.append(item)
    return {'items': items, 'complete': len(items) == len(report.source_ids)}


def report_plan_contexts(revisions):
    """Legacy snapshot projection retained for offline callers."""
    latest = {}
    for row in revisions:
        if row.work_id not in latest or latest[row.work_id].revision < row.revision:
            latest[row.work_id] = row
    from app.modules.work.content.document import plain_text
    return [{'sourceId': row.id, 'workId': row.work_id, 'title': row.content.get('title', ''),
             'bodyText': plain_text(row.content['body']) if row.content.get('body') is not None else row.content.get('bodyText', '')}
            for row in latest.values() if row.content.get('body') or row.content.get('bodyText')]
