"""Batch report projections without one revision/job query per list row."""
from collections import defaultdict

from sqlalchemy import select

from .models import Job, Member, ReportRevision
from .service import job_dto, problem


async def report_dtos(db, reports, actor):
    if not reports:
        return []
    if any(report.company_id != actor.company_id or (report.owner_id != actor.id and actor.role != 'admin') for report in reports):
        problem(404, '报告不存在或无权查看')
    identifiers = [report.id for report in reports]
    revisions = defaultdict(list)
    for revision in (await db.scalars(select(ReportRevision).where(ReportRevision.company_id == actor.company_id, ReportRevision.report_id.in_(identifiers)).order_by(ReportRevision.report_id, ReportRevision.revision.desc()))).all():
        revisions[revision.report_id].append(revision)
    own_ids = [report.id for report in reports if report.owner_id == actor.id]
    jobs = {}
    if own_ids:
        latest = select(Job).where(Job.company_id == actor.company_id, Job.owner_id == actor.id, Job.kind == 'report', Job.target_id.in_(own_ids)).distinct(Job.target_id).order_by(Job.target_id, Job.created_at.desc(), Job.id.desc())
        jobs = {job.target_id: job for job in (await db.scalars(latest)).all()}
    names = {actor.id: actor.name}
    other_owners = {report.owner_id for report in reports} - names.keys()
    if other_owners:
        names.update((await db.execute(select(Member.id, Member.name).where(Member.company_id == actor.company_id, Member.id.in_(other_owners)))).all())
    items = []
    for report in reports:
        history = revisions[report.id]
        own = actor.id == report.owner_id
        if not own and not history:
            problem(404, '报告尚未提交或无权查看')
        public = history[0] if history else None
        job = jobs.get(report.id)
        items.append({'id': report.id, 'ownerId': report.owner_id, 'ownerName': names.get(report.owner_id, ''), 'kind': report.kind, 'period': report.period, 'periodEnd': report.period_end, 'timezone': report.timezone, 'content': report.content if own else public.content, 'candidate': report.candidate if own else None, 'sourceIds': report.source_ids if own else public.source_ids, 'revision': report.revision if own else public.revision, 'publishedRevision': report.published_revision, 'managementRevision': report.revision, 'updatedAt': (report.updated_at if own else public.created_at).isoformat(), 'job': job_dto(job) if job else None, 'revisions': [{'revision': r.revision, 'content': r.content, 'sourceIds': r.source_ids, 'submittedAt': r.created_at.isoformat()} for r in history]})
    return items


async def report_dto(db, report, actor):
    return (await report_dtos(db, [report], actor))[0]
