"""Versioned task scope. Caller holds the company/owner lock before this row."""
from copy import deepcopy
from app.core.digests import digest
from app.core.errors import problem
from app.db.base import now
from app.modules.conversations.models import ConversationTaskState
from app.modules.messages.input_text import request_text
from app.modules.conversations.task_schemas import TaskInterpretation, TaskSource
from app.modules.messages.models import Message
from app.security.access import valid as business_valid
from app.tasks.models import Job
from sqlalchemy import select


async def store_for(db, actor, conversation_id):
    if not conversation_id:
        return None
    from app.modules.conversations.models import Conversation
    from app.security.ownership import owned
    await owned(db, Conversation, conversation_id, actor)
    row = await db.scalar(select(ConversationTaskState).where(
        ConversationTaskState.conversation_id == conversation_id,
        ConversationTaskState.company_id == actor.company_id,
        ConversationTaskState.owner_id == actor.id).with_for_update())
    if row is None:
        row = ConversationTaskState(conversation_id=conversation_id, company_id=actor.company_id, owner_id=actor.id, payload={})
        db.add(row)
        await db.flush()
    return row


async def begin_input(db, actor, message):
    row = await store_for(db, actor, message.conversation_id)
    if row:
        previous_id = row.payload.get('latestMessageId')
        if previous_id and previous_id != message.id:
            previous = await db.get(Message, previous_id)
            prior_job = await db.scalar(select(Job).where(Job.target_id == previous_id, Job.kind == 'message', Job.owner_id == actor.id))
            if previous and not previous.deleted and prior_job and prior_job.state in ('failed', 'awaiting_retry'):
                original = request_text(previous, prior_job)
                snapshot = prior_job.result.get('taskSnapshot', {})
                sources = snapshot.get('previousTask', {}).get('sources', []) if snapshot.get('relation') == 'continue' else []
                if original.strip():
                    sources = [*sources, TaskSource(messageId=previous.id, revision=previous.transcript_revision, digest=digest(original), quote=original[:2000]).model_dump()]
                sources = [sources[0], *sources[-15:]] if len(sources) > 16 else sources
                from app.tasks.items import collect
                row.payload = {**row.payload, 'task': {'id': snapshot.get('taskId', previous_id), 'messageId': previous_id, 'goal': original[:400], 'state': 'blocked', 'remaining': ['上次请求尚未完成'], 'sources': sources, 'items': collect(prior_job)}}
        row.revision += 1
        row.payload = {**row.payload, 'latestMessageId': message.id}
        row.updated_at = now()


async def source_text(db, actor, conversation_id, source):
    """Never authorize from assistant prose, attachment text or another owner."""
    try:
        source = TaskSource.model_validate(source)
    except ValueError:
        return None
    message = await db.get(Message, source.messageId)
    if not message or message.deleted or message.owner_id != actor.id or message.company_id != actor.company_id or message.conversation_id != conversation_id or message.transcript_revision != source.revision:
        return None
    if not await business_valid(db, actor, message.access):
        return None
    job = await db.scalar(select(Job).where(Job.kind == 'message', Job.target_id == message.id, Job.owner_id == actor.id))
    text = request_text(message, job)
    return text if digest(text) == source.digest and source.quote.strip() and source.quote in text else None


async def assert_current(db, actor, job, message):
    snapshot = job.result.get('taskSnapshot')
    if not snapshot or not message.conversation_id:
        return
    row = await store_for(db, actor, message.conversation_id)
    if row.payload.get('latestMessageId') != message.id:
        problem(409, '此消息之后已有新的请求，请继续当前会话；旧任务不会覆盖新指令', 'task_superseded')
    if snapshot.get('invalidated'):
        problem(409, '任务授权来源已失效，请重新说明要求', 'task_source_changed')
    if snapshot.get('version') != row.revision:
        problem(409, '会话任务范围已变化，请继续当前任务', 'task_superseded')
    if snapshot.get('inputRevision') != message.transcript_revision:
        from app.tasks.context import InputChanged
        raise InputChanged()
    for source in [*snapshot.get('directives', []), *snapshot.get('previousTask', {}).get('sources', [])]:
        if await source_text(db, actor, message.conversation_id, source) is None:
            problem(409, '任务指令来源已变化，请重新说明本次要求', 'task_source_changed')


async def freeze(db, actor, job, message):
    existing = job.result.get('taskSnapshot')
    if existing and existing.get('inputRevision') == message.transcript_revision:
        await assert_current(db, actor, job, message)
        return deepcopy(existing)
    row = await store_for(db, actor, message.conversation_id)
    payload = row.payload if row else {}
    # Legacy jobs acquire state lazily, without replaying any historical action.
    if row and payload.get('latestMessageId') not in (None, message.id):
        later = await db.get(Message, payload['latestMessageId'])
        if later and later.created_at > message.created_at:
            problem(409, '旧任务已有后续消息，请继续当前会话', 'task_superseded')
    if row and payload.get('latestMessageId') != message.id:
        row.payload = {**payload, 'latestMessageId': message.id}
        row.revision += 1
    directives = [source for source in payload.get('directives', []) if await source_text(db, actor, message.conversation_id, source) is not None]
    previous = payload.get('task', {})
    previous = previous if previous.get('state') in ('needs_input', 'partial', 'needs_confirmation', 'processing', 'blocked') else {}
    if previous and any([await source_text(db, actor, message.conversation_id, source) is None for source in previous.get('sources', [])]):
        previous = {}
    snapshot = {'version': row.revision if row else 1, 'taskId': message.id, 'messageId': message.id,
                'inputRevision': message.transcript_revision, 'directives': directives,
                'previousTask': deepcopy(previous), 'relation': 'new', 'allowLegacy': 'task' not in payload}
    job.result = {**job.result, 'taskSnapshot': snapshot}
    return deepcopy(snapshot)


async def resume(db, actor, job, message, *, requested):
    snapshot = await freeze(db, actor, job, message)
    previous = snapshot.get('previousTask', {})
    if requested and previous and previous.get('state') != 'cancelled':
        snapshot = {**snapshot, 'relation': 'continue', 'taskId': previous['id']}
        job.result = {**job.result, 'taskSnapshot': snapshot}
    return snapshot


async def apply_directive(db, actor, job, message, interpretation):
    """Persist a verified scope change before response delivery can fail."""
    value = TaskInterpretation.model_validate(interpretation or {})
    text = request_text(message, job)
    if value.directiveChange == 'keep' or not value.directiveQuote.strip() or value.directiveQuote not in text:
        return
    key = digest({'change': value.directiveChange, 'quote': value.directiveQuote})
    if job.result.get('appliedDirective') == key:
        return
    row = await store_for(db, actor, message.conversation_id)
    if not row or row.payload.get('latestMessageId') != message.id:
        return
    directives = [TaskSource(messageId=message.id, revision=message.transcript_revision, digest=digest(text),
        quote=value.directiveQuote, scope=value.directiveScope).model_dump()] if value.directiveChange == 'replace' else []
    row.payload = {**row.payload, 'directives': directives}
    row.revision += 1
    row.updated_at = now()
    snapshot = {**job.result['taskSnapshot'], 'version': row.revision, 'directives': directives}
    job.result = {**job.result, 'taskSnapshot': snapshot, 'appliedDirective': key}


async def finish(db, actor, job, message, interpretation, outcome):
    row = await store_for(db, actor, message.conversation_id)
    if not row or row.payload.get('latestMessageId') != message.id:
        return
    value = TaskInterpretation.model_validate(interpretation or {})
    # The same verified instruction may have been applied and bound to a target
    # during execution. Do not rebuild it from the final prose review and erase
    # that identity (or its authorized field set).
    await apply_directive(db, actor, job, message, value.model_dump())
    snapshot = job.result.get('taskSnapshot', {})
    directives = snapshot.get('directives', [])
    text = request_text(message, job)
    task_id = snapshot.get('taskId', message.id)
    if value.relation == 'continue' and snapshot.get('previousTask'):
        task_id = snapshot['previousTask']['id']
        snapshot = {**snapshot, 'relation': 'continue', 'taskId': task_id}
        job.result = {**job.result, 'taskSnapshot': snapshot}
    sources = snapshot.get('previousTask', {}).get('sources', []) if value.relation == 'continue' else []
    if text.strip():
        sources = [*sources, TaskSource(messageId=message.id, revision=message.transcript_revision, digest=digest(text), quote=text[:2000]).model_dump()]
    sources = [sources[0], *sources[-15:]] if len(sources) > 16 else sources
    from app.tasks.items import collect
    row.payload = {**row.payload, 'directives': directives, 'task': {
        'id': task_id, 'messageId': message.id, 'goal': value.goal or text[:400],
        'state': outcome['state'], 'remaining': outcome['remaining'],
        'question': value.remaining, 'completed': outcome['completed'],
        'sources': sources, 'items': collect(job)}}
    row.revision += 1
    row.updated_at = now()
    # A lost final status commit may resume THIS input without adopting a newer
    # message. The completed scope revision belongs to this same job.
    job.result = {**job.result, 'taskSnapshot': {**snapshot, 'version': row.revision, 'directives': directives}}


async def cancel(db, actor, job, message):
    row = await store_for(db, actor, message.conversation_id)
    if row and row.payload.get('latestMessageId') == message.id:
        row.payload = {**row.payload, 'task': {'id': job.result.get('taskSnapshot', {}).get('taskId', message.id),
            'messageId': message.id, 'state': 'cancelled', 'remaining': []}}
        row.revision += 1
        row.updated_at = now()


async def invalidate_sources(db, message_ids):
    """Remove only grants/tasks depending on corrected or removed user input."""
    if not message_ids:
        return
    messages = (await db.scalars(select(Message).where(Message.id.in_(message_ids)))).all()
    for message in messages:
        row = await db.scalar(select(ConversationTaskState).where(
            ConversationTaskState.conversation_id == message.conversation_id,
            ConversationTaskState.owner_id == message.owner_id).with_for_update())
        if not row:
            continue
        directives = row.payload.get('directives', [])
        kept = [source for source in directives if source['messageId'] not in message_ids]
        task = row.payload.get('task', {})
        affected = any(source['messageId'] in message_ids for source in task.get('sources', []))
        if len(kept) != len(directives) or affected:
            row.payload = {**row.payload, 'directives': kept, 'task': {} if affected else task}
            row.revision += 1
            row.updated_at = now()
        jobs = (await db.scalars(select(Job).where(Job.owner_id == message.owner_id, Job.company_id == message.company_id, Job.kind == 'message'))).all()
        for job in jobs:
            snapshot = deepcopy(job.result.get('taskSnapshot', {}))
            sources = [*snapshot.get('directives', []), *snapshot.get('previousTask', {}).get('sources', [])]
            if any(source['messageId'] in message_ids for source in sources):
                snapshot['directives'] = []
                snapshot['previousTask'] = {}
                snapshot['invalidated'] = True
                job.result = {**job.result, 'taskSnapshot': snapshot}


async def prepare_retry(db, actor, job, message):
    row = await store_for(db, actor, message.conversation_id)
    if row and row.payload.get('latestMessageId') not in (None, message.id):
        problem(409, '此消息之后已有新的请求，请继续当前会话', 'task_superseded')
    snapshot = job.result.get('taskSnapshot', {})
    if snapshot.get('inputRevision') != message.transcript_revision:
        # An explicit retry of corrected current input may take a new snapshot;
        # previously committed business receipts still retain their identities.
        job.result = {key: value for key, value in job.result.items() if key not in ('taskSnapshot', 'taskBarriers', 'toolOutcomes', 'taskInterpretation', 'intentTaskInterpretation')}
    else:
        await assert_current(db, actor, job, message)
