"""Authorized latest-prefix snapshots, independent from node/phase feedback."""
import re
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select
from app.db.base import now
from app.tasks.context import InputChanged
from app.tasks.feedback.feedback_state import update_feedback


def presentation_text(text):
    # Hold only internal citation syntax, including a split opening marker.
    # Ordinary Markdown links, brackets, HTML-as-text and code remain intact.
    text = re.sub(r'\[\[(?:file|business):[^\]]*\]\]', '（来源待核对）', text)
    start = text.rfind('[[')
    if start >= 0:
        tail = text[start:]
        if any(marker.startswith(tail) or tail.startswith(marker) for marker in ('[[file:', '[[business:')):
            text = text[:start]
    if text.endswith('['):
        text = text[:-1]
    return text


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


def failure_state(error):
    """Only ordinary transport failures can retain unconfirmed prose."""
    import asyncio
    import httpx
    from app.integrations.models.transport import ProviderError
    from app.tasks.retry import NodeFailed
    from sqlalchemy.exc import OperationalError, InterfaceError
    if isinstance(error, (OperationalError, InterfaceError, asyncio.CancelledError)):
        return 'interrupted'
    if isinstance(error, NodeFailed):
        code = error.failure.code
    elif isinstance(error, ProviderError):
        code = error.code
    elif isinstance(error, (httpx.TransportError, asyncio.TimeoutError)):
        code = 'network'
    else:
        code = ''
    return 'interrupted' if code in ('network', 'timeout', 'interrupted', 'rate_limit', 'provider_error') else 'withdrawn'


def source_snapshot(context, job):
    return {'sourceRevision': context.source_revision, 'documents': dict(context.document_versions),
            'images': dict(context.image_sources), 'reads': dict(context.read_versions),
            'deliverables': dict(job.result.get('deliverableSources', {})),
            'contextVersion': context.context_sources.get('invalidationVersion')}


async def validate_sources(db, actor, job, message, source):
    from app.modules.attachments.documents import agent_attachment, visible_attachment
    from app.security.versions import validate_cached_versions
    if source.get('sourceRevision') is not None and message.transcript_revision != source['sourceRevision']:
        raise InputChanged()
    if source.get('contextVersion') is not None:
        from app.modules.conversations.models import ConversationContext
        version = await db.scalar(select(ConversationContext.invalidation_version).where(
            ConversationContext.conversation_id == message.conversation_id,
            ConversationContext.company_id == actor.company_id, ConversationContext.owner_id == actor.id))
        if version != source['contextVersion']:
            raise InputChanged(context=True)
    await validate_cached_versions(db, actor, source.get('reads', {}))
    for identifier, revision in source.get('documents', {}).items():
        document = await agent_attachment(db, identifier, actor, job)
        if document.extraction_revision != revision:
            raise InputChanged(document=True)
    for identifier, parent in source.get('images', {}).items():
        image = await visible_attachment(db, identifier, actor)
        if image.message_id != parent:
            raise InputChanged(context=True)
    if job.result.get('sandboxSources'):
        from app.modules.executions.sources import check_sources
        await check_sources(db, actor, job.result['sandboxSources'])
    from app.modules.deliverables.queries import validate_sources as validate_deliverables
    return await validate_deliverables(db, actor, source.get('deliverables', {}), message.conversation_id)


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
    except (ValueError, HTTPException):
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
