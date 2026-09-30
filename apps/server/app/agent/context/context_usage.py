"""One conservative request estimator shared by enforcement, compaction and UI."""
import json
from langchain_core.messages import BaseMessage
from app.tasks.context import BudgetExceeded

THRESHOLD = .9
MAX_CONTEXT_BYTES = 16 * 1024 * 1024


def _size(value):
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(_size(item) for item in value)
    if isinstance(value, dict):
        if value.get('type') in ('image_url', 'image', 'input_image'):
            return 4096  # Image tile allowance, independent of binary/base64 length.
        return sum(len(str(key)) + _size(child) + 4 for key, child in value.items())
    return len(json.dumps(value, ensure_ascii=False, default=str))


def estimate_request(messages, tools=(), system=None):
    normalized = []
    for message in messages:
        if isinstance(message, BaseMessage):
            item = {'role': message.type, 'content': message.content}
            for key in ('tool_calls', 'tool_call_id', 'name'):
                value = getattr(message, key, None)
                if value:
                    item[key] = value
        else:
            item = message
        normalized.append(item)
    # One token per Unicode character intentionally overestimates most Latin text.
    # Include envelopes, tool schemas and tool arguments, not just visible prose.
    return _size(normalized) + _size(list(tools)) + (_size(system) if system else 0) + 16


def capacity(context):
    choice = (context.model_binding or {}).get(context.model_purpose) or {}
    return choice.get('contextCapability') or {'contextWindow': None, 'inputLimit': None, 'maxOutput': None, 'source': 'unknown'}


def input_budget(context, output_reserve=4000):
    cap = capacity(context)
    limits = [value for value in (cap.get('inputLimit'), (cap['contextWindow'] - output_reserve) if cap.get('contextWindow') else None) if value is not None]
    return max(0, min(limits)) if limits else None


def output_reserve(context, requested=4000):
    remaining = (32000 if context.node_retry else 8000) - context.output_tokens
    return max(0, min(4000, requested or 4000, capacity(context).get('maxOutput') or 4000, remaining))


def compression_reason(context, used, output_reserve=4000):
    cap = capacity(context)
    if cap.get('contextWindow') and used >= cap['contextWindow'] * THRESHOLD:
        return '上下文达到模型窗口的 90%'
    budget = input_budget(context, output_reserve)
    if budget is not None and used > budget:
        return '为本次输出预留空间，或达到服务商输入限制'
    return None


def ensure_input(context, used, output_reserve=4000):
    budget = input_budget(context, output_reserve)
    if budget is not None and used > budget:
        raise BudgetExceeded('本次输入超出模型可用上下文，请缩短本次内容或选择更大窗口的模型')
    if used > MAX_CONTEXT_BYTES:
        raise BudgetExceeded('本次上下文超过服务资源限制，请减少材料后重试')
