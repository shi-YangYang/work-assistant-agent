"""Reject legacy report operations before receipt replay or asynchronous work."""
from sqlalchemy import select
from app.modules.reports.models import Report
from app.modules.members.models import Member

MESSAGE = '正式日报已取消，原日报记录与操作已失效'


async def retired_action(db, actor, row):
    if row.result.get('reportRetired'):
        return True
    if not row.action.endswith('_report'):
        return False
    if row.params.get('kind') == 'daily':
        return True
    identifier = row.params.get('targetId') or row.result.get('objectId')
    if not identifier:
        return False
    query = select(Report).where(Report.id == identifier, Report.company_id == actor.company_id)
    if actor.role == 'admin':
        query = query.where(Report.owner_id.in_(select(Member.id).where(Member.company_id == actor.company_id, Member.role == 'employee')))
    else:
        query = query.where(Report.owner_id == actor.id)
    report = await db.scalar(query)
    return report is not None and report.kind != 'weekly'


async def report_job_available(db, job):
    if job.kind != 'report':
        return True
    return bool(await db.scalar(select(Report.id).where(Report.id == job.target_id, Report.company_id == job.company_id, Report.owner_id == job.owner_id, Report.deleted.is_(False), Report.kind == 'weekly')))
