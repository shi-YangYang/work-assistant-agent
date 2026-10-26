"""Deterministic report contract; prose semantics remain the writer's job."""
from app.core.digests import digest
from app.modules.reports.schemas import ReportContent

CONTRACT_VERSION = 1


def validate_content(content, *, require_nonempty=True):
    if not isinstance(content, dict) or set(content) != set(ReportContent.model_fields):
        raise ValueError('报告需要包含有效的四个栏目，原报告已保留')
    value = ReportContent.model_validate(content).model_dump()
    if require_nonempty and not any(text.strip() for text in value.values()):
        raise ValueError('报告内容不能为空，原报告已保留')
    return value


async def source_digest(db, report, actor, identifiers):
    from app.modules.reports.generation.sources import sources_for, source_payload
    rows = await sources_for(db, report, actor, identifiers)
    if not rows:
        raise ValueError('本周期暂无对应工作，请补充工作或手动填写报告')
    return digest({'version': CONTRACT_VERSION, 'kind': report.kind, 'period': report.period,
                   'periodEnd': report.period_end, 'timezone': report.timezone,
                   'items': await source_payload(db, rows)})
