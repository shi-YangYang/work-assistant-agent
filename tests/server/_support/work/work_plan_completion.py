"""Shared controlled fixtures extracted from test_work_plan_completion."""
from types import SimpleNamespace


def job_value():
    return SimpleNamespace(target_id='message', result={}, state='succeeded', error='')


def card(**changes):
    return {'id': 'receipt', 'messageId': 'message', 'action': 'update_work', 'state': 'succeeded',
            'objectId': 'work', 'objectRevision': 2, 'changedFields': ['bodyEdits', 'nextStep'], **changes}
