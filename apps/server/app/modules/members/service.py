from app.core.errors import problem
from app.modules.members.models import Member
from sqlalchemy import select


async def visible_member(db, actor, member_id, *, employee_only=False):
    target = await db.scalar(select(Member).where(Member.id == member_id, Member.company_id == actor.company_id))
    if target is None or (employee_only and target.role != 'employee') or (actor.role != 'admin' and actor.id != target.id):
        problem(404, '成员不存在或无权查看')
    return target
