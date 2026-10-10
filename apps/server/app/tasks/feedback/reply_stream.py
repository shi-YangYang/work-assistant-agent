"""Authorized latest-prefix snapshots, independent from node/phase feedback."""
from datetime import timedelta
from fastapi import HTTPException
from app.db.base import now
from app.tasks.feedback.feedback_state import update_feedback


from app.tasks.streaming.lifecycle import presentation_text, failure_state, source_snapshot, validate_sources


def transition(job, state, *, new=False):
    old = (job.feedback or {}).get('replyStream')
    if not old:
        return
    withdrawn = state == 'withdrawn' or job.access.get('team', False)
    value = {**old, 'version': 1, 'state': 'withdrawn' if withdrawn else state,
             'text': '' if withdrawn else old['text'],
             'generation': old['generation'] + int(new)}
    job.feedback = {**job.feedback, 'replyStream': value}
    update_feedback(job)


def retire(job):
    old = (job.feedback or {}).get('replyStream')
    job.feedback = {key: value for key, value in (job.feedback or {}).items()
                    if key not in ('replyStream', 'replyStreamSource', 'replyStreamCall')}
    if old and old['state'] == 'withdrawn':
        job.feedback = {**job.feedback, 'replyStream': old}

async def dto(db, actor, job, message):
    from app.integrations.models.transport import ProviderError
    from app.security.access import valid
    from app.modules.messages.service import active_message
    value = (job.feedback or {}).get('replyStream') if job else None
    if not value or value.get('version') != 1:
        return None
    allowed = (actor.active and actor.id == job.owner_id == message.owner_id
               and actor.company_id == job.company_id == message.company_id
               and not job.access.get('team') and not message.access.get('team')
               and job.access.get('role', actor.role) == actor.role and not message.deleted
               and job.updated_at >= now() - timedelta(days=1))
    try:
        if not allowed or not await valid(db, actor, job.access) or not await valid(db, actor, message.access):
            raise ValueError('Unavailable reply')
        await active_message(db, message.id, actor)
        if await validate_sources(db, actor, job, message, (job.feedback or {}).get('replyStreamSource', {})):
            raise ValueError('Team source requires complete review')
    except (ValueError, HTTPException, ProviderError):
        return {'version': 1, 'generation': value['generation'], 'state': 'withdrawn', 'text': ''}
    state = value.get('state')
    if state not in ('streaming', 'finalizing', 'interrupted', 'withdrawn'):
        return None
    return {'version': 1, 'generation': value['generation'], 'state': state,
            'text': presentation_text(value.get('text', '')) if state != 'withdrawn' else ''}


# Kept at this import path for existing callers and old checkpoint fixtures.
from app.tasks.streaming.publisher import ReplyPublisher


async def persist_snapshot(db, actor, job, message, value, *, state='interrupted'):
    """Called under the current job lock. No Redis/network wait inside transaction."""
    from app.integrations.models.transport import ProviderError
    if not value or value.get('sealed') or (value.get('attempt'), value.get('fence')) != (job.attempt, job.fence):
        return
    if value.get('callId') != (job.feedback or {}).get('replyStreamCall'):
        return
    if value.get('generation') != (job.feedback or {}).get('replyStream', {}).get('generation'):
        return
    allowed = (state == 'interrupted' and actor.active and actor.role == job.access.get('role', actor.role)
               and not job.access.get('team') and not message.access.get('team'))
    try:
        from app.security.access import valid
        if not await valid(db, actor, job.access) or not await valid(db, actor, message.access):
            allowed = False
        if await validate_sources(db, actor, job, message, value.get('source', {})):
            allowed = False
    except (ValueError, HTTPException, ProviderError):
        allowed = False
    job.feedback = {**job.feedback, 'replyStreamSource': value.get('source', {}),
                    'replyStream': {'version': 1, 'generation': value['generation'],
                                    'state': 'interrupted' if allowed else 'withdrawn',
                                    'text': value.get('text', '') if allowed else ''}}
    update_feedback(job)


async def temporary_snapshot(settings, job):
    from app.tasks.streaming.protocol import Identity
    from app.tasks.streaming.redis_store import store_for, StreamUnavailable
    identity = Identity(job.company_id, job.owner_id, job.id, job.attempt, job.fence)
    try:
        return await store_for(settings).snapshot(identity)
    except StreamUnavailable:
        return None


async def clear_temporary(settings, job):
    from app.tasks.streaming.protocol import Identity
    from app.tasks.streaming.redis_store import store_for, StreamUnavailable
    try:
        await store_for(settings).seal(Identity(job.company_id, job.owner_id, job.id, job.attempt, job.fence))
    except StreamUnavailable:
        pass


async def freeze_temporary(settings, job):
    from app.tasks.streaming.protocol import Identity
    from app.tasks.streaming.redis_store import store_for, StreamUnavailable
    try:
        await store_for(settings).freeze(Identity(job.company_id, job.owner_id, job.id, job.attempt, job.fence))
    except StreamUnavailable:
        pass
