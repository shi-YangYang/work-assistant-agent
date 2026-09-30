"""Confirmation policy, independent from identity and business authorization."""
from dataclasses import dataclass
from typing import Literal

ExecutionMode = Literal['ask', 'auto', 'full']
MODES = ('ask', 'auto', 'full')
SENSITIVE = frozenset({'delete_work', 'submit_report', 'delete_report'})


@dataclass(frozen=True)
class Decision:
    outcome: Literal['allow', 'ask', 'deny']
    reason: str


def decide(mode: ExecutionMode, action: str, *, authorized=True, explicitly_confirm=False, approved=False):
    if not authorized:
        return Decision('deny', '当前任务未授权该操作')
    if approved:
        return Decision('allow', '本次操作已获明确批准')
    if mode == 'ask' or explicitly_confirm or mode != 'full' and action in SENSITIVE:
        return Decision('ask', '逐项确认' if mode == 'ask' else '请核对本次操作')
    return Decision('allow', '')


def effective(snapshot, current):
    """Retries cannot acquire elevated authority, lowering applies immediately."""
    return MODES[min(MODES.index(snapshot if snapshot in MODES else 'auto'), MODES.index(current if current in MODES else 'auto'))]


async def mode_for(db, job, conversation_id):
    from app.modules.conversations.models import Conversation
    conversation = await db.get(Conversation, conversation_id) if conversation_id else None
    current = conversation.execution_mode if conversation else 'auto'
    if 'executionMode' not in job.result:
        job.result = {**job.result, 'executionMode': 'auto', 'modeRevision': 1}
    return effective(job.result['executionMode'], current)
