from paa_server.core.errors import problem
from paa_server.modules.members.models import Member
from paa_server.modules.support.models import SupportFeedback
from sqlalchemy import select


def dto(item, owner_name):
    return {
        'id': item.id, 'ownerId': item.owner_id, 'ownerName': owner_name,
        'description': item.description, 'diagnostics': item.diagnostics,
        'state': item.state, 'handlingNote': item.handling_note,
        'revision': item.revision, 'createdAt': item.created_at.isoformat(),
        'updatedAt': item.updated_at.isoformat(),
    }


def visible(actor):
    query = select(SupportFeedback, Member.name).join(
        Member, (Member.id == SupportFeedback.owner_id) & (Member.company_id == actor.company_id),
    ).where(SupportFeedback.company_id == actor.company_id)
    if actor.role != 'admin':
        query = query.where(SupportFeedback.owner_id == actor.id)
    return query


async def record(db, actor, identifier, *, lock=False):
    query = visible(actor).where(SupportFeedback.id == identifier)
    if lock:
        query = query.with_for_update(of=SupportFeedback)
    row = (await db.execute(query)).first()
    if row is None:
        problem(404, '反馈不存在或无权查看')
    return row
