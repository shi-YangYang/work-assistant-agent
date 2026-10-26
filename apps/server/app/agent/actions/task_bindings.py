"""Pure snapshot guards shared by work planning and task-item recovery."""
from app.core.digests import digest


STALE_BINDING = '事项尝试已变化，本次授权未核对新增内容，本次未执行；请根据完整事项重新核对后重试。'


def recovery_plan_state(job, target, key='workChangeCandidates'):
    state = job.result.get(key, {})
    return {name: state.get(name) for name in ('version', 'scope', 'messageId')} | {
        'target': state.get('targets', {}).get(target)}


def recovery_binding_error(job, binding):
    proof = binding.get('workRecovery')
    if not proof:
        return ''
    if (digest(recovery_plan_state(job, proof['target'])) != proof['plan']
            or digest(recovery_plan_state(job, proof['target'], 'workChangeRequirements')) != proof['selectedPlan']):
        return STALE_BINDING
    items = {item['id']: item for item in job.result.get('taskItems', [])}
    for identifier, original in proof['items'].items():
        outcomes = {entry['key']: digest(entry) for entry in job.result.get('toolOutcomes', []) if entry.get('taskItemId') == identifier}
        barriers = {key: digest(value) for key, value in job.result.get('taskBarriers', {}).items() if value.get('taskItemId') == identifier}
        if (digest(items.get(identifier)) != original['snapshot']
                or outcomes != original['outcomes'] or barriers != original['barriers']):
            return STALE_BINDING
    return ''
