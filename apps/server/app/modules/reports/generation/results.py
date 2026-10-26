from app.db.base import now
from app.modules.reports.models import Report
from app.security.ownership import owned
from app.tasks.feedback.feedback_state import update_feedback
from app.tasks.lease import lease


async def save_candidate(db, context, content):
    job, actor = await lease(db, context)
    if job.kind != 'report':
        raise ValueError('请在我的报告中准备报告')
    from app.security.locks import company_lock
    await company_lock(db, actor.company_id)
    report = await owned(db, Report, job.target_id, actor, lock=True)
    if job.result.get('reportSaved'):
        return
    source_ids = job.result.get('sourceIds', [])
    from app.modules.reports.generation.validation import CONTRACT_VERSION, source_digest, validate_content
    content = validate_content(content)
    current_digest = await source_digest(db, report, actor, source_ids)
    draft = job.result.get('reportDraft', {})
    if draft.get('contractVersion') != CONTRACT_VERSION or draft.get('sourceDigest') != current_digest:
        raise ValueError('报告来源已变化，请重新生成；原报告已保留')
    if report.revision != job.base_revision or report.edited or report.published_revision:
        report.candidate = {'content': content, 'sourceIds': source_ids}
    else:
        report.content, report.source_ids = content, source_ids
    report.revision += 1
    report.updated_at = now()
    job.result = {**job.result, 'reportSaved': True, 'reportFlow': 2, 'savedRevision': report.revision}
    job.state, job.phase, job.error, job.lease_until, job.updated_at = 'succeeded', 'complete', '', None, now()
    update_feedback(job, 'complete', '')
    from app.modules.reports.scheduling.schedule import draft_ready
    await draft_ready(db, report)

    from app.modules.operations.mutations.report_completion import complete_report
    await complete_report(db, actor, job)
