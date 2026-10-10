"""Source validity and stream presentation shared by publishers and feedback."""
import re
from sqlalchemy import select
from app.tasks.context import InputChanged


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
    return 'interrupted' if code in ('network', 'timeout', 'interrupted', 'rate_limit', 'provider_error', 'stopped') else 'withdrawn'


def source_snapshot(context, job):
    return {'sourceRevision': context.source_revision, 'documents': dict(context.document_versions),
            'images': dict(context.image_sources), 'reads': dict(context.read_versions),
            'deliverables': dict(job.result.get('deliverableSources', {})),
            'contextVersion': context.context_sources.get('invalidationVersion')}


async def validate_sources(db, actor, job, message, source, *, refresh_work_versions=None):
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
    await validate_cached_versions(db, actor, source.get('reads', {}), refresh_work_versions=refresh_work_versions)
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
