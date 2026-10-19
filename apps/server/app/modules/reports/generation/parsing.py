import json
import logging
from app.modules.reports.schemas import ReportContent
from pydantic import ValidationError


def invalid_report(answer, reason, message, on_timing):
    finish = answer.response_metadata.get('finish_reason')
    fields = {'reason': reason, 'finish_reason': finish if finish in ('stop', 'length', 'content_filter', None) else 'other',
              'body_chars': len(answer.content) if isinstance(answer.content, str) else None,
              'tool_count': len(answer.tool_calls)}
    if on_timing:
        on_timing('report.invalid_response', **fields)
    else:
        logging.getLogger('paa.company').warning('report.invalid_response %s', json.dumps(fields))
    return ValueError(message)


def parse_report(answer, *, on_timing=None):
    if answer.response_metadata.get('finish_reason') in ('length', 'content_filter'):
        raise invalid_report(answer, 'finish_reason', '报告响应被截断或拦截，原报告已保留，请重试', on_timing)
    if answer.tool_calls or not isinstance(answer.content, str):
        raise invalid_report(answer, 'message_structure', '报告返回格式不正确，原报告已保留，请重试', on_timing)
    text = answer.content.strip()
    if text.startswith('```json') and text.endswith('```'):
        text = text[7:-3].strip()
    reason = 'report_json'
    try:
        body = json.loads(text)
        reason = 'report_fields'
        if not isinstance(body, dict) or set(body) != {'completed', 'ongoing', 'blockers', 'next'}:
            raise ValueError()
        reason = 'report_schema'
        content = ReportContent.model_validate(body).model_dump()
        reason = 'report_empty'
        if not any(value.strip() for value in content.values()):
            raise ValueError()
    except (ValueError, ValidationError, TypeError):
        raise invalid_report(answer, reason, '报告需要包含有效的四个栏目，原报告已保留，请重试', on_timing) from None
    return content
