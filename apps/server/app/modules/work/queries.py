from app.core.errors import problem
from app.core.pagination import cursor_decode, cursor_encode
from app.modules.messages.service import deleted_sources
from app.modules.team.sources import business_link_dtos
from app.modules.work.models import WorkItem, WorkRevision
from app.modules.work.serializers import work_dto
from app.security.access import require as business_require, valid as business_valid
from app.security.ownership import owned
from sqlalchemy import or_, select


def status_filter(status):
    if status not in ('', 'in_progress', 'blocked', 'done'):
        problem(422, '工作状态无效')


def work_search(query):
    term = query.strip()
    return or_(WorkItem.title.icontains(term, autoescape=True), *(WorkItem.content[key].astext.icontains(term, autoescape=True) for key in ('summary', 'blocker', 'nextStep')))


async def work_page(db, actor, owner_id, q='', status='', cursor=None, limit=20):
    status_filter(status)
    query = select(WorkItem).where(WorkItem.company_id == actor.company_id, WorkItem.owner_id == owner_id, WorkItem.deleted.is_(False))
    if q.strip():
        query = query.where(work_search(q))
    if status:
        query = query.where(WorkItem.content['status'].astext == status)
    visible = []
    boundary = cursor_decode(cursor) if cursor else None
    # Authorization may reject an arbitrarily long run of rows. Keep scanning
    # until a complete visible page (plus lookahead) or the actual end is found.
    while len(visible) <= limit:
        statement = query
        if boundary:
            stamp, identifier = boundary
            statement = statement.where((WorkItem.updated_at < stamp) | ((WorkItem.updated_at == stamp) & (WorkItem.id < identifier)))
        rows = list((await db.scalars(statement.order_by(WorkItem.updated_at.desc(), WorkItem.id.desc()).limit(100))).all())
        for row in rows:
            if await business_valid(db, actor, row.access, retained=True):
                visible.append(row)
                if len(visible) > limit:
                    break
        if len(rows) < 100 or len(visible) > limit:
            break
        boundary = rows[-1].updated_at, rows[-1].id
    return {'items': [work_dto(row) for row in visible[:limit]], 'nextCursor': cursor_encode(visible[limit - 1].updated_at, visible[limit - 1].id) if len(visible) > limit else None}


async def work_item_query(identifier, revision, actor, db):
    item = await owned(db, WorkItem, identifier, actor, read=True)
    await business_require(db, actor, item.access, retained=True)
    history = (await db.scalars(select(WorkRevision).where(WorkRevision.work_id == item.id).order_by(WorkRevision.revision.desc()).limit(100))).all()
    dto = work_dto(item)
    if revision is not None:
        from app.modules.work.serializers import revision_work
        selected = await db.scalar(select(WorkRevision).where(WorkRevision.work_id == item.id, WorkRevision.revision == revision))
        if not selected or not await business_valid(db, actor, selected.access, retained=True):
            problem(404, '工作修订不存在或无权查看')
        dto = revision_work(item, selected)
        history = [row for row in history if row.revision <= revision]
    return {**dto, 'businessLinks': await business_link_dtos(db, actor, selected.business_links if revision is not None else item.business_links), 'history': [{'id': r.id, 'revision': r.revision, 'content': r.content, 'sourceIds': r.source_ids, 'deletedSourceIds': await deleted_sources(db, r.source_ids), 'createdAt': r.created_at.isoformat()} for r in history if await business_valid(db, actor, r.access, retained=True)]}
