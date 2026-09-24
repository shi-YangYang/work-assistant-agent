from app.core.errors import problem
from app.modules.attachments.models import Attachment
from app.modules.messages.models import Message
from app.modules.reports.models import Report, ReportRevision
from app.modules.work.models import WorkItem, WorkRevision
from app.security.access import require as business_require
from sqlalchemy import select


async def deletion_impact(db, item, actor):
    if isinstance(item, WorkItem):
        await business_require(db, actor, item.access, retained=True)
        return {'revision': item.revision, 'messages': 0, 'attachments': 0, 'messageIds': [], 'attachmentIds': []}
    if actor.role != 'admin' and item.published_revision:
        problem(403, '已提交的报告不能删除')
    if actor.role == 'admin':
        from app.modules.members.models import Member
        owner = await db.get(Member, item.owner_id)
        if not owner or owner.role != 'employee' or owner.company_id != actor.company_id:
            problem(404, '报告不存在或无权查看')
    revisions = (await db.scalars(select(ReportRevision).where(ReportRevision.report_id == item.id))).all()
    ids = set(item.source_ids) | set((item.candidate or {}).get('sourceIds', []))
    for revision in revisions:
        ids.update(revision.source_ids)
    sources = (await db.scalars(select(WorkRevision).where(WorkRevision.id.in_(ids), WorkRevision.owner_id == item.owner_id, WorkRevision.company_id == actor.company_id))).all()
    messages = {mid for source in sources for mid in source.source_ids} if actor.role == 'admin' else set()
    message_ids = sorted((await db.scalars(select(Message.id).where(Message.id.in_(messages), Message.deleted.is_(False), Message.owner_id == item.owner_id))).all())
    attachment_ids = sorted((await db.scalars(select(Attachment.id).where(Attachment.message_id.in_(message_ids), Attachment.deleted.is_(False), Attachment.owner_id == item.owner_id))).all())
    return {'messages': len(message_ids), 'attachments': len(attachment_ids), 'revision': item.revision, 'messageIds': message_ids, 'attachmentIds': attachment_ids}


async def remove_record(db, actor, kind, identifier, expected):
    from app.modules.operations.deletion import target, remove_report, remove_work
    item = await target(db, WorkItem if kind == 'work' else Report, identifier, actor, expected)
    if not item.deleted:
        await deletion_impact(db, item, actor)
        if kind == 'work':
            await remove_work(db, item)
        else:
            await remove_report(db, item, actor)
    return item
