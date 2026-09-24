from paa_server.core.errors import problem
from paa_server.modules.members.models import Member
from sqlalchemy import select


async def owned(db, model, identifier, actor, *, read=False, lock=False):
    query = select(model).where(model.id == identifier, model.company_id == actor.company_id)
    if not read or actor.role != 'admin':
        query = query.where(model.owner_id == actor.id)
    else:
        employees = select(Member.id).where(Member.company_id == actor.company_id, Member.role == 'employee')
        query = query.where((model.owner_id == actor.id) | model.owner_id.in_(employees))
    if hasattr(model, 'deleted'):
        query = query.where(model.deleted.is_(False))
    if lock:
        owner_id = await db.scalar(query.with_only_columns(model.owner_id))
        if owner_id:
            await db.scalar(select(Member).where(Member.id == owner_id).with_for_update())
        query = query.with_for_update()
    item = await db.scalar(query)
    if item is None:
        problem(404, '记录不存在或无权查看')
    return item
