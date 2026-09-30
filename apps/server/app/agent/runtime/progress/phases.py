"""Phase names reflect orchestration boundaries, never inferred thoughts."""
from langchain_core.messages import HumanMessage, ToolMessage


def model_phase(messages, job_id, *, nested=False):
    latest = next((message for message in reversed(messages) if isinstance(message, HumanMessage)), None)
    if latest and latest.id in (f'delivery-repair:{job_id}', f'completion-repair:{job_id}'):
        return '完善答复'
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            if message.id in (f'delivery-repair:{job_id}', f'completion-repair:{job_id}'):
                return '完善答复'
            return '处理请求' if nested else '理解请求'
        if isinstance(message, ToolMessage):
            return '整理工具结果'
    return '处理请求'
