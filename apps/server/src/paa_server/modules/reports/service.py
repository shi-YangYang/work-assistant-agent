from paa_server.core.errors import problem
from paa_server.core.versions import version
from paa_server.db.base import now
from paa_server.modules.members.models import Company, Member
from paa_server.modules.reports.models import Report, ReportRevision
from paa_server.modules.reports.periods import period
from paa_server.modules.reports.schemas import ReportContent
from paa_server.modules.reports.sources import report_inputs
from paa_server.security.ownership import owned
from paa_server.tasks.models import Job
from sqlalchemy import select


async def ensure_report(db, actor, kind, day, *, scheduled=False, report_timezone=None):
    if actor.role != 'employee':
        problem(403, '管理员不生成个人报告')
    company = await db.get(Company, actor.company_id)
    start, end = period(kind, day)
    await db.scalar(select(Member).where(Member.id == actor.id).with_for_update())
    report = await db.scalar(select(Report).where(Report.owner_id == actor.id, Report.kind == kind, Report.period == start.isoformat()))
    if report is None:
        report = Report(company_id=actor.company_id, owner_id=actor.id, kind=kind, period=start.isoformat(), period_end=end.isoformat(), timezone=report_timezone or company.rules['timezone'], content={'completed': '', 'ongoing': '', 'blockers': '', 'next': ''})
        db.add(report)
        await db.flush()
    from paa_server.modules.reports.schedule import link_report
    await link_report(db, report)
    if report.deleted:
        if scheduled:
            return report, None
        problem(409, '该周期报告已删除，不能重新生成')
    existing = await db.scalar(select(Job).where(Job.owner_id == actor.id, Job.kind == 'report', Job.target_id == report.id).order_by(Job.created_at.desc()).limit(1))
    if existing is not None and (scheduled or existing.state in ('queued', 'running')):
        return report, existing
    inputs = await report_inputs(db, report)
    job = Job(company_id=actor.company_id, owner_id=actor.id, kind='report', target_id=report.id, base_revision=report.revision, state='queued' if inputs else 'succeeded', phase='saved' if inputs else 'empty', result={'sourceIds': [r.id for r in inputs], 'reportFlow': 2})
    db.add(job)
    await db.flush()
    return report, job


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
    from paa_server.modules.reports.schedule import link_report
    await link_report(db, report, submitted=True)
    return report
