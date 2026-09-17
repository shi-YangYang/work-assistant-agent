"""The same transactional business rules for page forms and assistant tools."""
from sqlalchemy import func, select
from . import business_access as business
from .models import Attachment, Message, Report, ReportRevision, WorkItem, WorkRevision, now
from .schemas import Progress, ReportContent
from .service import active_message, owned, problem, version


async def save_work(db, actor, patch, *, identifier=None, expected=None, sources=(), origin='manual', links=(), access=None):
    await business.company_lock(db, actor.company_id)
    if identifier:
        work = await owned(db, WorkItem, identifier, actor, lock=True)
        await business.require(db, actor, work.access, retained=True)
        version(work, expected)
        content = Progress.model_validate({**work.content, **patch}).model_dump(mode='json')
    else:
        content = Progress.model_validate(patch).model_dump(mode='json')
        work = WorkItem(company_id=actor.company_id, owner_id=actor.id, title=content['title'], content=content, origin=origin)
        db.add(work)
        await db.flush()
    if not content['title'].strip():
        problem(422, '请填写工作标题')
    for source in sources:
        message = await active_message(db, source, actor)
        await business.require(db, actor, message.access)
        business.inherit(actor, work, message, include_message_links=True)
    if access:
        work.access = business.merge_access(work.access or business.scope(actor), access)
    work.business_links = business.merge_links(work.business_links, list(links))
    if identifier and content == work.content and not links and (not sources or origin == 'assistant'):
        return work
    if identifier:
        work.revision += 1
    work.content, work.title, work.updated_at = content, content['title'], now()
    db.add(WorkRevision(company_id=actor.company_id, owner_id=actor.id, work_id=work.id, revision=work.revision, content=content, source_ids=list(sources), access=work.access, business_links=work.business_links))
    await db.flush()
    return work


async def edit_report(db, actor, identifier, expected, patch):
    if actor.role != 'employee':
        problem(403, '管理员不编辑个人报告')
    report = await owned(db, Report, identifier, actor, lock=True)
    version(report, expected)
    content = ReportContent.model_validate({**report.content, **patch}).model_dump()
    if content != report.content:
        report.content, report.edited, report.updated_at = content, True, now()
        report.revision += 1
    return report


async def submit_report(db, actor, identifier, expected):
    if actor.role != 'employee':
        problem(403, '管理员不提交个人报告')
    report = await owned(db, Report, identifier, actor, lock=True)
    version(report, expected)
    if report.published_revision == report.revision:
        return report
    if not any(str(v).strip() for v in report.content.values()):
        problem(422, '请先填写报告内容')
    db.add(ReportRevision(company_id=actor.company_id, owner_id=actor.id, report_id=report.id, revision=report.revision, content=report.content, source_ids=report.source_ids))
    report.published_revision, report.updated_at = report.revision, now()
    from .report_schedule import link_report
    await link_report(db, report, submitted=True)
    return report


async def deletion_impact(db, item, actor):
    if isinstance(item, WorkItem):
        await business.require(db, actor, item.access, retained=True)
        return {'revision': item.revision, 'messages': 0, 'attachments': 0, 'messageIds': [], 'attachmentIds': []}
    if actor.role != 'admin' and item.published_revision:
        problem(403, '已提交的报告不能删除')
    if actor.role == 'admin':
        from .models import Member
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
    from .deletion import target, remove_report, remove_work
    item = await target(db, WorkItem if kind == 'work' else Report, identifier, actor, expected)
    if not item.deleted:
        await deletion_impact(db, item, actor)
        if kind == 'work':
            await remove_work(db, item)
        else:
            await remove_report(db, item, actor)
    return item
