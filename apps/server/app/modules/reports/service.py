from app.core.errors import problem
from app.core.versions import version
from app.db.base import now
from app.modules.members.models import Company, Member
from app.modules.reports.models import Report, ReportRevision
from app.modules.reports.periods import period
from app.modules.reports.schemas import ReportContent
from app.modules.reports.generation.sources import report_inputs
from app.security.ownership import owned
from app.security.locks import company_lock
from app.tasks.models import Job
from sqlalchemy import select


def no_report_sources_message(kind, start, end):
    label = '周报' if kind == 'weekly' else '日报'
    scope = str(start) if kind == 'daily' else f'{start} 至 {end}'
    return f'{scope} 暂无可用于生成{label}的工作记录。请先核对汇报周期，再确认该周期内是否有有效工作进展；只有工作正文或计划还不能生成报告。也可以让我根据当前会话整理一份{label}正文。'


async def ensure_report(db, actor, kind, day, *, scheduled=False, report_timezone=None, instructions='', instruction_source=None):
    await company_lock(db, actor.company_id)
    member = await db.scalar(select(Member).where(Member.id == actor.id).with_for_update().execution_options(populate_existing=True))
    if not member or not member.active or member.role != 'employee':
        problem(403, '当前账号不能生成个人报告')
    company = await db.get(Company, actor.company_id)
    start, end = period(kind, day)
    query = select(Report).where(Report.owner_id == actor.id, Report.kind == kind, Report.period == start.isoformat())
    report = await db.scalar(query.where(Report.deleted.is_(False)))
    from app.modules.reports.scheduling.schedule import link_report
    if report is None and scheduled:
        tombstone = await db.scalar(query.where(Report.deleted.is_(True)).order_by(Report.created_at.desc(), Report.id.desc()).limit(1))
        if tombstone:
            await link_report(db, tombstone, cancelled=True)
            return tombstone, None
    new_report = report is None
    if report is None:
        report = Report(company_id=actor.company_id, owner_id=actor.id, kind=kind, period=start.isoformat(), period_end=end.isoformat(), timezone=report_timezone or company.rules['timezone'], content={'completed': '', 'ongoing': '', 'blockers': '', 'next': ''})
    existing = None if new_report else await db.scalar(select(Job).where(Job.owner_id == actor.id, Job.kind == 'report', Job.target_id == report.id).order_by(Job.created_at.desc()).limit(1))
    if existing is not None and (scheduled or existing.state in ('queued', 'running')):
        prior_source = existing.result.get('instructionSource') or {}
        if instructions and (instructions != existing.result.get('instructions', '') or (instruction_source or {}).get('references', []) != prior_source.get('references', [])):
            problem(409, '该报告正在生成，新的写作要求尚未应用，请完成后再修改或重新生成')
        await link_report(db, report, restore=not scheduled)
        return report, existing
    inputs = await report_inputs(db, report)
    if not inputs:
        if scheduled:
            return (None if new_report else report), None
        problem(422, no_report_sources_message(kind, start, end), 'report_sources_empty')
    if new_report:
        db.add(report)
        await db.flush()
    await link_report(db, report, restore=not scheduled)
    job = Job(company_id=actor.company_id, owner_id=actor.id, kind='report', target_id=report.id, base_revision=report.revision, state='queued', phase='saved', result={'sourceIds': [r.id for r in inputs], 'reportFlow': 2, **({'instructions': instructions} if instructions else {}), **({'instructionSource': instruction_source} if instruction_source else {})})
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
    from app.modules.reports.scheduling.schedule import link_report
    await link_report(db, report, submitted=True)
    return report
