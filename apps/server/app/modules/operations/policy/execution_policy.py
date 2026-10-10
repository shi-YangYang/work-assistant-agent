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


def sensitive(action: str, changes=None):
    if action in SENSITIVE:
        return True
    if action != 'update_work':
        return False
    changes = changes or {}
    update = changes.get('update') or {}
    return 'removeMaterial' in changes or isinstance(update, dict) and update.get('action') == 'delete'


def decide(mode: ExecutionMode, action: str, *, changes=None, authorized=True, explicitly_confirm=False, approved=False):
    if not authorized:
        return Decision('deny', '当前任务未授权该操作')
    if approved:
        return Decision('allow', '本次操作已获明确批准')
    if mode == 'ask' or explicitly_confirm or mode != 'full' and sensitive(action, changes):
        return Decision('ask', '逐项确认' if mode == 'ask' else '请核对本次操作')
    return Decision('allow', '')


def effective(snapshot, current):
    """Retries cannot acquire elevated authority, lowering applies immediately."""
    return MODES[min(MODES.index(snapshot if snapshot in MODES else 'auto'), MODES.index(current if current in MODES else 'auto'))]


async def current_mode(db, owner_id, company_id):
    from sqlalchemy import select
    from app.modules.members.models import Member
    return await db.scalar(select(Member.execution_mode).where(Member.id == owner_id, Member.company_id == company_id)) or 'auto'


async def mode_for(db, job):
    current = await current_mode(db, job.owner_id, job.company_id)
    if 'executionMode' not in job.result:
        job.result = {**job.result, 'executionMode': 'auto', 'modeRevision': 1}
    return effective(job.result['executionMode'], current)
