"""A business snapshot is public content, not a grant to its private conversation."""
from app.core.errors import problem
from app.modules.attachments.models import Attachment
from app.modules.messages.models import Message
from app.modules.work.models import WorkItem, WorkRevision
from app.security.ownership import owned
from sqlalchemy import select


async def selected_attachments(db, actor, ids, conversation_id):
    if len(ids) > 4 or len(set(ids)) != len(ids):
        problem(422, '最多附带四份明确选中的材料')
    rows = []
    for identifier in ids:
        attachment = await owned(db, Attachment, identifier, actor)
        message = await owned(db, Message, attachment.message_id, actor)
        if message.conversation_id != conversation_id:
            problem(404, '附带材料不属于当前会话')
        rows.append({'id': attachment.id, 'name': attachment.name, 'kind': attachment.kind})
    return rows


def snapshot(content, *, message_ids=(), reference=None, attachments=()):
    return {'scope': 'selected', 'content': content, 'originMessageIds': list(message_ids), 'deliverable': reference or {}, 'attachmentIds': list(attachments)}


async def published_attachment(db, attachment, *, revision_ids=None):
    statement = select(WorkRevision.id).join(WorkItem, WorkItem.id == WorkRevision.work_id).where(WorkRevision.company_id == attachment.company_id, WorkRevision.owner_id == attachment.owner_id, WorkItem.deleted.is_(False), WorkRevision.publication['attachmentIds'].contains([attachment.id]))
    if revision_ids is not None:
        statement = statement.where(WorkRevision.id.in_(revision_ids))
    return await db.scalar(statement.limit(1))


async def shared_attachment(db, actor, attachment):
    from app.modules.members.models import Member
    if actor.role != 'admin':
        return False
    owner = await db.get(Member, attachment.owner_id)
    if not owner or owner.role != 'employee' or owner.company_id != actor.company_id:
        return False
    return bool(await db.scalar(select(WorkRevision.id).join(WorkItem, WorkItem.id == WorkRevision.work_id).where(WorkRevision.company_id == actor.company_id, WorkRevision.owner_id == attachment.owner_id, WorkItem.deleted.is_(False), WorkRevision.access['team'].as_boolean().is_not(True), WorkRevision.publication['attachmentIds'].contains([attachment.id])).limit(1)))
