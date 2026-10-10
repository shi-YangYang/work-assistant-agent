"""Pure, clock-injected budget calculations. No public API representation."""
import copy
from app.tasks.context import BudgetExceeded
from .policy import DEFAULT, LEGACY, Policy


class TaskBudgetStopped(BudgetExceeded):
    def __init__(self, reason):
        super().__init__('本次整理尚未完成，已保存的结果会保留。')
        self.reason = reason


def policy(state):
    return Policy(**state['policy'])


def create(round_id, instant, *, legacy=None, configured=None):
    chosen = LEGACY if legacy else configured or DEFAULT
    deadline = legacy.get('deadline', instant + chosen.seconds) if legacy else instant + chosen.seconds
    return {'version': 1, 'round': round_id, 'policy': chosen.dump(),
            'startedAt': deadline - chosen.seconds, 'deadlineAt': deadline, 'endedAt': None,
            'tools': sum(row.get('kind') == 'tool' for row in legacy.get('nodes', []) if row.get('scope') == legacy.get('scope')) if legacy else 0,
            'models': legacy.get('actualCalls', 0) if legacy else 0,
            'toolReservations': [row['id'] for row in legacy.get('nodes', []) if row.get('scope') == legacy.get('scope') and row.get('kind') == 'tool'] if legacy else [], 'phase': 'working', 'reason': ''}


def snapshot(state, instant):
    value = copy.deepcopy(state)
    limits = policy(value)
    remaining = max(0, value['deadlineAt'] - instant)
    if value['endedAt'] is not None:
        value['phase'] = 'ended'
    elif remaining <= 0 or value['models'] >= limits.models:
        value.update(phase='exhausted', reason='time' if remaining <= 0 else 'models')
    elif value.get('phase') == 'finalizing':
        pass
    elif value['tools'] >= limits.tools or value['models'] >= limits.models - limits.reserve_models or remaining <= limits.reserve_seconds:
        value.update(phase='finalizing', reason='tools' if value['tools'] >= limits.tools else 'models' if value['models'] >= limits.models - limits.reserve_models else 'time')
    elif limits.tools - value['tools'] <= limits.warn_tools or limits.models - value['models'] <= limits.warn_models or remaining <= limits.warn_seconds:
        value['phase'] = 'near_limit'
    value['remainingSeconds'] = remaining
    return value


def reserve(state, kind, instant, *, identity=None, final_answer=False, admitted_tool=False):
    value = snapshot(state, instant)
    value.pop('remainingSeconds')
    if value['phase'] in ('exhausted', 'ended'):
        raise TaskBudgetStopped(value['reason'] or 'ended')
    if kind == 'tool' and identity in value['toolReservations']:
        return value
    limits = policy(value)
    finishing_tool = (kind == 'model' and admitted_tool and value['reason'] == 'tools'
                      and value['models'] < limits.models - limits.reserve_models
                      and value['deadlineAt'] - instant > limits.reserve_seconds)
    if value['phase'] == 'finalizing' and not finishing_tool and (kind == 'tool' or not final_answer):
        raise TaskBudgetStopped(value['reason'])
    if kind == 'tool':
        value['tools'] += 1
        value['toolReservations'].append(identity)
    else:
        value['models'] += 1
    # The request that crosses a threshold is admitted, including its in-flight
    # child work. The next reservation must use the new phase.
    return value
