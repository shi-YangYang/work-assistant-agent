"""Retain work file snapshots while live records or report snapshots reference them."""
from sqlalchemy import select
from app.modules.work.models import WorkItem, WorkMaterial, WorkRevision
from app.modules.attachments.models import Attachment
from app.modules.reports.models import Report, ReportRevision


async def report_retains_work(db, work):
    revisions = set((await db.scalars(select(WorkRevision.id).where(WorkRevision.work_id == work.id))).all())
    reports = (await db.execute(select(Report.source_ids, Report.candidate).where(Report.owner_id == work.owner_id, Report.company_id == work.company_id, Report.deleted.is_(False)))).all()
    sources = [ids for source_ids, candidate in reports for ids in (source_ids, (candidate or {}).get('sourceIds', []))]
    sources += (await db.scalars(select(ReportRevision.source_ids).join(Report, Report.id == ReportRevision.report_id).where(Report.owner_id == work.owner_id, Report.company_id == work.company_id, Report.deleted.is_(False)))).all()
    return any(revisions.intersection(ids) for ids in sources)


async def retire_work_files(db, work):
    if await report_retains_work(db, work):
        return
    rows = (await db.scalars(select(Attachment).join(WorkMaterial, WorkMaterial.attachment_id == Attachment.id).where(WorkMaterial.work_id == work.id))).all()
    for row in rows:
        row.deleted = True


async def retire_orphans(db):
    works = (await db.scalars(select(WorkItem).where(WorkItem.deleted.is_(True), WorkItem.id.in_(select(WorkMaterial.work_id).join(Attachment, Attachment.id == WorkMaterial.attachment_id).where(Attachment.deleted.is_(False)))))).all()
    for work in works:
        await retire_work_files(db, work)
