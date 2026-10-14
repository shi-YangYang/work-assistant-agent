"""Bounded, durable image slots; no prompts or provider credentials in feedback."""
from app.tasks.feedback.feedback_state import update_feedback


def update(job, operation, **values):
    slots = job.result.get('imageGeneration', [])
    changed = [({**slot, **values} if slot['operation'] == operation and slot['state'] != 'ready' else slot)
               for slot in slots]
    if changed != slots:
        job.result = {**job.result, 'imageGeneration': changed}
        update_feedback(job)


def dto(job):
    slots = job.result.get('imageGeneration', [])
    if job.state in ('queued', 'running'):
        return slots
    # A cancelled/crashed attempt must not leave an endless animation on reload.
    return [{**slot, 'state': ('cancelled' if job.state == 'cancelled' else
                             'interrupted' if slot['state'] == 'generating' else 'not_started')}
            if slot['state'] in ('queued', 'generating') else slot for slot in slots]


async def register(context, operations):
    from app.tasks.lease import lease
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        slots = {slot['operation']: slot for slot in job.result.get('imageGeneration', [])}
        for operation in operations:
            if slots.get(operation, {}).get('state') != 'ready':
                slots[operation] = {'operation': operation, 'state': 'queued'}
        job.result = {**job.result, 'imageGeneration': [slots[key] for key in sorted(slots)]}
        update(job, operations[0], state='generating')
        update_feedback(job)


async def advance(context, operation, result, remaining, *, stop=False):
    from app.tasks.lease import lease
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        state = result.get('state')
        delivery = result.get('delivery') or {}
        values = {'state': {'succeeded': 'ready', 'retryable': 'interrupted', 'running': 'interrupted',
                            'unknown': 'unknown', 'cancelled': 'cancelled'}.get(state, 'failed')}
        if delivery.get('id'):
            values.update(deliverableId=delivery['id'], revision=delivery['revision'])
        update(job, operation, **values)
        if stop:
            for pending in remaining:
                update(job, pending, state='not_started')
        elif remaining:
            update(job, remaining[0], state='generating')
