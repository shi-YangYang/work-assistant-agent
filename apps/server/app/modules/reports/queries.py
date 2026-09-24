from collections import defaultdict
from app.core.errors import problem
from app.modules.members.models import Member
from app.modules.messages.service import deleted_sources
from app.modules.reports.models import Report, ReportRevision
from app.modules.work.models import WorkItem, WorkRevision
from app.security.ownership import owned
from app.tasks.models import Job
from app.tasks.serializers import job_dto
from sqlalchemy import select


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


async def reports_query(kind, cursor, actor, db):
    if actor.role != 'employee':
        problem(403, '管理员通过团队查看员工报告')
    query = select(Report).where(Report.deleted.is_(False), Report.owner_id == actor.id, Report.kind == kind)
    if cursor:
        query = query.where(Report.period < cursor)
    rows = (await db.scalars(query.order_by(Report.period.desc()).limit(51))).all()
    return {'items': await report_dtos(db, rows[:50], actor), 'nextCursor': rows[49].period if len(rows) > 50 else None}


async def get_report_query(identifier, revision, actor, db):
    report = await owned(db, Report, identifier, actor, read=True)
    dto = await report_dto(db, report, actor)
    if revision is not None:
        selected = next((row for row in dto['revisions'] if row['revision'] == revision), None)
        if not selected:
            problem(404, '报告修订不存在或无权查看')
        dto.update(content=selected['content'], sourceIds=selected['sourceIds'], revision=revision, publishedRevision=revision, updatedAt=selected['submittedAt'], historical=True)
    return dto


async def report_sources_query(identifier, revision, actor, db):
    report = await owned(db, Report, identifier, actor, read=True)
    dto = await report_dto(db, report, actor)
    if revision is not None and revision != dto['revision']:
        historical = next((row for row in dto['revisions'] if row['revision'] == revision), None)
        if not historical:
            problem(404, '报告修订不存在或无权查看')
        dto = historical
    sources = (await db.scalars(select(WorkRevision).where(WorkRevision.id.in_(dto['sourceIds']), WorkRevision.company_id == actor.company_id, WorkRevision.owner_id == report.owner_id))).all()
    return {'items': [{'id': r.id, 'workId': r.work_id, 'title': r.content['title'], 'revision': r.revision, 'sourceIds': r.source_ids, 'deletedSourceIds': await deleted_sources(db, r.source_ids), 'workDeleted': (await db.get(WorkItem, r.work_id)).deleted} for r in sources]}
