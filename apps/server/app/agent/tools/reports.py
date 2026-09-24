from langchain.tools import ToolRuntime, tool
from app.db.base import now
from app.modules.reports.models import Report
from app.modules.reports.schemas import ReportContent
from app.security.ownership import owned
from app.tasks.context import RunContext
from app.tasks.lease import lease


@tool
async def draft_report(completed: str, ongoing: str, blockers: str, next: str, runtime: ToolRuntime[RunContext]) -> str:
    """Save a report candidate from the supplied confirmed revisions; never publish a report."""
    content = ReportContent(completed=completed, ongoing=ongoing, blockers=blockers, next=next).model_dump(mode='json', exclude_unset=True)
    context = runtime.context
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        if job.kind != 'report':
            return '请让员工在“我的报告”选择日期并生成报告。'
        report = await owned(db, Report, job.target_id, actor, lock=True)
        if job.result.get('reportSaved'):
            return '报告草稿已保存，等待员工审阅。'
        source_ids = job.result.get('sourceIds', [])
        if report.revision != job.base_revision or report.edited or report.published_revision:
            report.candidate = {'content': content, 'sourceIds': source_ids}
        else:
            report.content, report.source_ids = content, source_ids
        # Candidates also change the source material included in deletion. A
        # confirmation opened before this write must not authorize those sources.
        report.revision += 1
        report.updated_at = now()
        job.result = {**job.result, 'reportSaved': True}
        return '报告草稿已保存，等待员工审阅；尚未发布。'
