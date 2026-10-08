"""Authorized latest-prefix snapshots, independent from node/phase feedback."""
import re
import time
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
    value = {**old, 'state': 'withdrawn' if withdrawn else state,
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


class ReplyPublisher:
    def __init__(self, context, call_id):
        self.context, self.call_id = context, call_id
        self.generation = None
        self.at = 0
        self.text = ''

    async def start(self):
        from app.tasks.lease import lease
        async with self.context.sessions.begin() as db:
            job, _ = await lease(db, self.context)
            old = (job.feedback or {}).get('replyStream', {})
            self.generation = old.get('generation', 0) + 1
            job.feedback = {**(job.feedback or {}), 'replyStreamCall': self.call_id,
                            'replyStreamSource': source_snapshot(self.context, job),
                            'replyStream': {'version': 1, 'generation': self.generation, 'state': 'withdrawn', 'text': ''}}
            update_feedback(job)

    async def write(self, text, *, state='streaming', force=False):
        instant = time.monotonic()
        if not force and (text == self.text or instant - self.at < .2):
            return
        from app.tasks.lease import lease
        from app.modules.messages.models import Message
        async with self.context.sessions.begin() as db:
            job, actor = await lease(db, self.context)
            if job.feedback.get('replyStreamCall') != self.call_id:
                return
            message = await db.get(Message, job.target_id)
            source = source_snapshot(self.context, job)
            team = await validate_sources(db, actor, job, message, source)
            if team or job.access.get('team') or message.access.get('team'):
                text, state = '', 'withdrawn'
            job.feedback = {**job.feedback, 'replyStreamSource': source,
                            'replyStream': {'version': 1, 'generation': self.generation, 'state': state, 'text': text}}
            update_feedback(job)
        self.at, self.text = instant, text

    async def withdraw(self):
        await self.write('', state='withdrawn', force=True)

    async def fail(self, error, text=None):
        # Cancellation/lease loss is sealed by the owner of the new fence.
        from app.tasks.context import LostLease
        try:
            await self.write((self.text if text is None else text) if failure_state(error) == 'interrupted' else '',
                             state=failure_state(error), force=True)
        except (LostLease, InputChanged, HTTPException, ValueError):
            pass
