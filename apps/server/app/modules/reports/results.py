from app.db.base import now
from app.modules.reports.models import Report
from app.modules.reports.sources import sources_for
from app.security.ownership import owned
from app.tasks.feedback_state import update_feedback
from app.tasks.lease import lease


async def save_candidate(db, context, content):
    job, actor = await lease(db, context)
    if job.kind != 'report':
        raise ValueError('请在我的报告中准备报告')
    report = await owned(db, Report, job.target_id, actor, lock=True)
    if job.result.get('reportSaved'):
        return
    source_ids = job.result.get('sourceIds', [])
    await sources_for(db, report, actor, source_ids)
    if not source_ids:
        raise ValueError('暂无已确认工作，请补充工作或手动填写报告')
    if report.revision != job.base_revision or report.edited or report.published_revision:
        report.candidate = {'content': content, 'sourceIds': source_ids}
    else:
        report.content, report.source_ids = content, source_ids
    report.revision += 1
    report.updated_at = now()
    job.result = {**job.result, 'reportSaved': True, 'reportFlow': 2, 'savedRevision': report.revision}
    job.state, job.phase, job.error, job.lease_until, job.updated_at = 'succeeded', 'complete', '', None, now()
    update_feedback(job, 'complete', '')
    from app.modules.reports.schedule import draft_ready
    await draft_ready(db, report)
