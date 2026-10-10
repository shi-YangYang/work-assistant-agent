"""A small optional preview header; task state and business receipts stay separate."""

MARKER = '<!--noria:'
HEADER_LIMIT = 1024
PROSE_POLICY = '''最终正文直接完整交付，首行 <!--noria:{}--> 后换行；仅当本次请求仍有未完成项时，在同一标记填写 remaining，例如 <!--noria:{"remaining":["未完成的具体事项及原因"]}-->，不为此另调工具。普通追问、建议和未来可选事项不算未完成。标记不展示，工具前说明不用；无需 finish_task 或任务元数据表单。\n'''


def parse_header(raw, *, complete=False):
    """Return (prose, optional unfinished scope, marked); hold incomplete headers."""
    value = raw.lstrip()
    if MARKER.startswith(value) and not value.startswith(MARKER):
        if complete and value:
            raise ValueError('最终正文标记不完整')
        return '', None, False
    if not value.startswith(MARKER):
        return raw, None, False
    end = value.find('-->', len(MARKER))
    if end < 0:
        if complete or len(value) > HEADER_LIMIT:
            raise ValueError('最终正文标记不完整')
        return '', None, True
    if end > HEADER_LIMIT:
        raise ValueError('最终正文标记过长')
    from app.integrations.models.stream_events import tool_arguments
    header = tool_arguments(value[len(MARKER):end])
    if not isinstance(header, dict) or set(header) - {'length', 'remaining'}:
        raise ValueError('最终正文标记无效')
    # Read old preview headers without turning their metadata into a new
    # instruction, local length gate, or another model call.
    remaining = header.get('remaining', [])
    if not isinstance(remaining, list) or len(remaining) > 8 or any(not isinstance(item, str) or not item.strip() or len(item) > 240 for item in remaining):
        raise ValueError('未完成范围无效')
    task = {'state': 'blocked', 'remaining': remaining} if remaining else None
    return value[end + 3:].lstrip('\r\n'), task, True


def task_for(job, task=None):
    """Server-observed budget refusals cannot be cleared by final prose."""
    from app.modules.conversations.task.task_schemas import TaskInterpretation
    value = TaskInterpretation.model_validate(task or {})
    blocked = job.result.get('nodeExecution', {}).get('budgetBlockedTools', [])
    if blocked:
        remaining = list(dict.fromkeys([*value.remaining, *blocked]))
        if len(remaining) > 8:
            remaining = [*remaining[:7], '；'.join(remaining[7:])]
        value = value.model_copy(update={'state': 'blocked', 'remaining': remaining})
    return value
