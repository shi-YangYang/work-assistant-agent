from sqlalchemy import select
from app.core.errors import problem
from app.core.versions import version
from app.db.base import now
from app.modules.work.models import WorkUpdate, WorkUpdateRevision


def update_dto(row):
    return {'id': row.id, 'workId': row.work_id, 'revision': row.revision, 'text': row.text, 'materialIds': row.material_ids, 'origin': row.origin, 'ownerId': row.owner_id, 'createdAt': row.created_at.isoformat(), 'updatedAt': row.updated_at.isoformat(), 'deleted': row.deleted, 'workRevision': row.work_revision}


async def save_update(db, actor, work, text, materials, origin, *, identifier=None, expected=None, deleted=False, created_at=None):
    if identifier:
        row = await db.scalar(select(WorkUpdate).where(WorkUpdate.id == identifier, WorkUpdate.work_id == work.id, WorkUpdate.owner_id == actor.id).with_for_update())
        if not row or row.deleted:
            problem(404, '进展不存在或已删除')
        version(row, expected)
        row.revision += 1
    else:
        row = WorkUpdate(company_id=actor.company_id, owner_id=actor.id, work_id=work.id, revision=1, created_at=created_at or now())
        db.add(row)
    row.text, row.material_ids, row.origin, row.deleted = text, list(materials), origin, deleted
    row.work_revision, row.updated_at = work.revision, now()
    await db.flush()
    db.add(WorkUpdateRevision(company_id=actor.company_id, owner_id=actor.id, update_id=row.id, revision=row.revision, text=text, material_ids=list(materials), deleted=deleted, work_revision=work.revision, origin=origin))
    return row


async def update_page(db, work, start=0, limit=20, *, revision=None):
    if revision is None:
        rows = list((await db.scalars(select(WorkUpdate).where(WorkUpdate.work_id == work.id, WorkUpdate.deleted.is_(False)).order_by(WorkUpdate.created_at.desc(), WorkUpdate.id.desc()).offset(start).limit(limit + 1))).all())
        return {'items': [update_dto(row) for row in rows[:limit]], 'nextCursor': start + limit if len(rows) > limit else None}
    # Resolve each entry at the selected work revision, never use today's text.
    latest = select(WorkUpdateRevision).join(WorkUpdate, WorkUpdate.id == WorkUpdateRevision.update_id).where(WorkUpdate.work_id == work.id, WorkUpdateRevision.work_revision <= revision).distinct(WorkUpdateRevision.update_id).order_by(WorkUpdateRevision.update_id, WorkUpdateRevision.revision.desc()).subquery()
    from sqlalchemy.orm import aliased
    snap = aliased(WorkUpdateRevision, latest)
    rows = (await db.execute(select(WorkUpdate, snap).join(snap, snap.update_id == WorkUpdate.id).where(snap.deleted.is_(False)).order_by(WorkUpdate.created_at.desc(), WorkUpdate.id.desc()).offset(start).limit(limit + 1))).all()
    return {'items': [{**update_dto(row), 'revision': s.revision, 'text': s.text, 'materialIds': s.material_ids, 'origin': s.origin, 'updatedAt': s.created_at.isoformat(), 'workRevision': s.work_revision, 'deleted': False} for row, s in rows[:limit]], 'nextCursor': start + limit if len(rows) > limit else None}
