from datetime import date
from app.core.errors import problem
from app.core.versions import version
from app.db.base import now
from app.db.idempotency import Idempotency, idem_begin, idem_save
from sqlalchemy import delete, select
from app.modules.reports.models import Report, ReportObligation
from app.modules.reports.queries import report_dto
from app.modules.reports.service import ensure_report, submit_report as writes_submit_report
from app.tasks.models import Job
from app.security.ownership import owned


async def generation_begin(db, actor, action, key, payload):
    if actor.role != 'employee':
        problem(403, '管理员不生成个人报告')
    prior, digest = await idem_begin(db, actor, action, key, payload)
    if prior:
        report = await db.scalar(select(Report).where(Report.id == prior.get('reportId'), Report.owner_id == actor.id, Report.company_id == actor.company_id, Report.deleted.is_(False), Report.kind == 'weekly'))
        if report is None:
            # Historical prepare receipts predate deletion-time cache cleanup.
            await db.execute(delete(Idempotency).where(Idempotency.owner_id == actor.id, Idempotency.action == action, Idempotency.key == key))
            prior = None
    return prior, digest


async def prepare_obligation_command(identifier, idempotency_key, actor, db):
    prior, digest = await generation_begin(db, actor, 'prepare-obligation:' + identifier, idempotency_key, {})
    obligation = await owned(db, ReportObligation, identifier, actor, lock=True)
    if prior:
        return prior
    # The current employee's manual entry depends on an active report, not the
    # historical obligation state. idem_begin holds the company/member locks.
    report = await db.scalar(select(Report).where(Report.company_id == actor.company_id, Report.owner_id == actor.id, Report.kind == obligation.kind, Report.period == obligation.period, Report.deleted.is_(False)))
    if report:
        job = await db.scalar(select(Job).where(Job.target_id == report.id, Job.kind == 'report').order_by(Job.created_at.desc(), Job.id.desc()).limit(1))
    else:
        report, job = await ensure_report(db, actor, obligation.kind, date.fromisoformat(obligation.period), report_timezone=obligation.timezone)
    return idem_save(db, actor, 'prepare-obligation:' + identifier, idempotency_key, digest, {'reportId': report.id, 'jobId': job.id if job else None})


async def adopt_candidate_command(identifier, body, actor, db):
    if actor.role != 'employee':
        problem(403, '管理员不编辑个人报告')
    report = await owned(db, Report, identifier, actor, lock=True)
    version(report, body.expectedRevision)
    if not report.candidate:
        problem(409, '没有待采用的生成结果')
    report.content = report.candidate['content']
    report.source_ids = report.candidate['sourceIds']
    report.candidate, report.edited, report.updated_at = None, True, now()
    report.revision += 1
    return await report_dto(db, report, actor)


async def submit_command(identifier, body, idempotency_key, actor, db):
    if actor.role != 'employee':
        problem(403, '管理员不提交个人报告')
    await owned(db, Report, identifier, actor)
    action = f'submit:{identifier}'
    prior, digest = await idem_begin(db, actor, action, idempotency_key, body.model_dump())
    if prior:
        return prior
    report = await writes_submit_report(db, actor, identifier, body.expectedRevision)
    return idem_save(db, actor, action, idempotency_key, digest, {'ok': True, 'revision': report.revision})
