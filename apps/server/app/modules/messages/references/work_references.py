"""A message selects one owned work; it never grants additional access."""
from fastapi import HTTPException
from app.core.errors import problem
from app.modules.work.models import WorkItem
from app.security.access import valid
from sqlalchemy import select


async def require_work(db, actor, identifier):
    item = await db.scalar(select(WorkItem).where(WorkItem.id == identifier,
        WorkItem.company_id == actor.company_id, WorkItem.owner_id == actor.id,
        WorkItem.deleted.is_(False)).execution_options(populate_existing=True))
    if not item or not await valid(db, actor, item.access, retained=True):
        problem(404, '引用的工作已删除或无权查看，请移除或重新选择工作', 'work_reference_unavailable')
    return item


async def reference_dto(db, actor, reference):
    if not reference:
        return None
    identifier = reference['workId']
    try:
        item = await require_work(db, actor, identifier)
        return {'workId': item.id, 'title': item.title, 'unavailable': False}
    except HTTPException:
        return {'workId': identifier, 'unavailable': True}
