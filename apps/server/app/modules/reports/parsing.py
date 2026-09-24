import json
from app.modules.reports.schemas import ReportContent
from pydantic import ValidationError


def parse_report(answer):
    if answer.response_metadata.get('finish_reason') in ('length', 'content_filter'):
        raise ValueError('报告响应被截断或拦截，原报告已保留，请重试')
    if answer.tool_calls or not isinstance(answer.content, str):
        raise ValueError('报告返回格式不正确，原报告已保留，请重试')
    text = answer.content.strip()
    if text.startswith('```json') and text.endswith('```'):
        text = text[7:-3].strip()
    try:
        body = json.loads(text)
        if not isinstance(body, dict) or set(body) != {'completed', 'ongoing', 'blockers', 'next'}:
            raise ValueError()
        content = ReportContent.model_validate(body).model_dump()
        if not any(value.strip() for value in content.values()):
            raise ValueError()
    except (ValueError, ValidationError, TypeError):
        raise ValueError('报告需要包含有效的四个栏目，原报告已保留，请重试') from None
    return content
