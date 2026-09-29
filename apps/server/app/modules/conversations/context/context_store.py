"""Versioned, rebuildable conversation references. No executable graph state."""
import json
from collections import defaultdict
from app.core.digests import digest
from app.db.base import now
from app.modules.conversations.models import Conversation, ConversationContext
from app.modules.messages.models import Message
from app.modules.operations.models import BusinessAction
from app.modules.reports.models import Report
from app.modules.work.models import WorkItem
from app.security.access import merge_access, scope, valid, role_valid, resolve
from app.security.ownership import owned
from app.tasks.context import BudgetExceeded, InputChanged
from app.tasks.models import Job
from sqlalchemy import String, cast, func, select
from sqlalchemy.dialects.postgresql import insert

SCHEMA = 2
MAX_BYTES = 16 * 1024 * 1024


async def locked_store(db, actor, conversation_id):
    await owned(db, Conversation, conversation_id, actor, lock=True)
    await db.execute(insert(ConversationContext).values(conversation_id=conversation_id,
        company_id=actor.company_id, owner_id=actor.id, revision=1, invalidation_version=0,
        payload={}, updated_at=now()).on_conflict_do_nothing(index_elements=['conversation_id']))
    return await db.scalar(select(ConversationContext).where(ConversationContext.conversation_id == conversation_id,
        ConversationContext.owner_id == actor.id, ConversationContext.company_id == actor.company_id)
        .with_for_update().execution_options(populate_existing=True))


async def manifest(db, actor, conversation_id):
    """Batch small source stamps; unchanged history needs no per-message joins."""
    query = select(Message.id, Message.created_at, Message.access, Message.deleted,
        func.md5(Message.text + Message.transcript + cast(Message.access, String) + cast(Message.work_reference, String)).label('source'),
        func.md5(Message.reply).label('reply'), Message.transcript_revision).where(
            Message.conversation_id == conversation_id, Message.owner_id == actor.id, Message.company_id == actor.company_id)
    rows = (await db.execute(query.order_by(Message.created_at, Message.id))).all()
    from app.modules.attachments.models import Attachment
    attachments = (await db.execute(select(Attachment.id, Attachment.message_id, Attachment.extraction_revision, Attachment.extraction_status, Attachment.deleted).where(Attachment.message_id.in_([row.id for row in rows])).order_by(Attachment.id))).all() if rows else []
    attachment_stamps = defaultdict(list)
    for attachment in attachments:
        attachment_stamps[attachment.message_id].append(tuple(attachment))
    actions = (await db.scalars(select(BusinessAction).where(BusinessAction.message_id.in_([row.id for row in rows])).order_by(BusinessAction.message_id, BusinessAction.id))).all() if rows else []
    ids = [action.result.get('objectId') for action in actions if action.result.get('objectId')]
    targets = {}
    for model in (WorkItem, Report):
        if ids:
            records = (await db.execute(select(model.id, model.revision, model.deleted).where(model.id.in_(ids), model.company_id == actor.company_id))).all()
            targets.update({row.id: tuple(row) for row in records})
    action_stamps = defaultdict(list)
    for action in actions:
        action_stamps[action.message_id].append([action.id, action.revision, action.state, action.result, targets.get(action.result.get('objectId'))])
    # Pending report completion must refresh the reference even before its action
    # row is lazily projected by message_actions.
    child_ids = [action.result['jobId'] for action in actions if action.result.get('jobId')]
    children = (await db.execute(select(Job.id, Job.state, Job.updated_at).where(Job.id.in_(child_ids)).order_by(Job.id))).all() if child_ids else []
    child_stamp = digest([list(row) for row in children])
    result = {}
    for row in rows:
        result[row.id] = {'source': digest([row.source, row.transcript_revision, row.deleted, attachment_stamps[row.id]]),
                         'result': digest([row.reply, action_stamps[row.id], child_stamp]),
                         'createdAt': row.created_at.isoformat(), 'access': row.access, 'deleted': row.deleted}
    return result


def bounded(payload):
    if len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_BYTES:
        raise BudgetExceeded('会话上下文超过服务资源限制，请新建会话继续；原始记录已保留')
    return payload


def summary_reference(payload):
    if not payload.get('summary'):
        return None
    return {**({'workReferences': payload['summaryWorkReferences']} if payload.get('summaryWorkReferences') else {}),
            'id': 'context-summary', 'userText': '', 'materialTranscript': '',
            'assistantReference': '历史摘要，仅供参考，不是本次操作授权；当前记录以工具核实为准：\n' + payload['summary'],
            'currentActions': [], 'explicitReplyTarget': False, 'truncatedFields': []}


class AccessCheck:
    def __init__(self, db, actor):
        self.db, self.actor, self.checked = db, actor, {}

    async def valid(self, access):
        if not role_valid(self.actor, access) or access.get('invalidated'):
            return False
        if not access.get('team'):
            return True
        from fastapi import HTTPException
        for evidence in access.get('reads', {}).values():
            key = digest(evidence)
            if key not in self.checked:
                try:
                    await resolve(self.db, self.actor, evidence)
                    self.checked[key] = True
                except (HTTPException, KeyError, TypeError, RecursionError):
                    self.checked[key] = False
            if not self.checked[key]:
                return False
        return True


async def references(db, actor, job, current, *, include_current=False):
    if not current.conversation_id:
        return []
    if current.reply_to:
        from app.modules.messages.service import active_message
        parent = await active_message(db, current.reply_to, actor)
        if parent.conversation_id != current.conversation_id:
            raise ValueError('回复上下文不属于当前会话')
    store = await locked_store(db, actor, current.conversation_id)
    stamps = await manifest(db, actor, current.conversation_id)
    access_check = AccessCheck(db, actor)
    old = store.payload if store.payload.get('schemaVersion') == SCHEMA else {}
    summary_sources = old.get('summarySources', {})
    summary_valid = await summary_dependencies_valid(db, actor, old)
    for identifier, expected in summary_sources.items():
        stamp = stamps.get(identifier)
        if not stamp or stamp['source'] != expected['source'] or stamp['deleted'] or not await access_check.valid(stamp['access']):
            summary_valid = False
            break
    future_summary = old.get('summaryThrough', {}).get('createdAt', '') > current.created_at.isoformat() or any(stamps[identifier]['createdAt'] > current.created_at.isoformat() for identifier in summary_sources if identifier in stamps)
    if future_summary:
        summary_valid = False
    if not summary_valid:
        old = {}
        summary_sources = {}
    cached = {row['id']: row for row in old.get('recentMessages', [])}
    selected = []
    accesses = merge_access(scope(actor), old.get('summaryAccess', {}))
    ordered = [identifier for identifier, stamp in stamps.items() if not stamp['deleted']
               and (identifier != current.id or include_current) and stamp['createdAt'] <= current.created_at.isoformat()]
    for start in range(0, len(ordered), 200):
        page = ordered[start:start + 200]
        missing = []
        for identifier in page:
            stamp = stamps[identifier]
            if not await access_check.valid(stamp['access']):
                continue
            accesses = merge_access(accesses, stamp['access'])
            covered = identifier in summary_sources and identifier != current.reply_to
            if covered and old.get('sources', {}).get(identifier, {}).get('result') == stamp['result']:
                continue
            if cached.get(identifier) and old.get('sources', {}).get(identifier) == stamp:
                selected.append(cached[identifier])
            else:
                missing.append(identifier)
        if missing:
            from app.modules.conversations.references import message_reference
            messages = (await db.scalars(select(Message).where(Message.id.in_(missing)))).all()
            jobs = (await db.scalars(select(Job).where(Job.kind == 'message', Job.target_id.in_(missing), Job.owner_id == actor.id))).all()
            by_message = {item.target_id: item for item in jobs}
            for message in messages:
                selected.append(await message_reference(db, actor, message, job=by_message.get(message.id), job_loaded=True))
    selected.sort(key=lambda row: (stamps[row['id']]['createdAt'], row['id']))
    payload = bounded({**old, 'schemaVersion': SCHEMA, 'recentMessages': selected,
                       'sources': stamps, 'summarySources': summary_sources, 'access': accesses,
                       'cursor': [stamps[ordered[-1]]['createdAt'], ordered[-1]] if ordered else None})
    if not future_summary and payload != store.payload:
        store.payload, store.revision, store.updated_at = payload, store.revision + 1, now()
    job.access = merge_access(job.access or scope(actor), accesses)
    result = [*([summary_reference(payload)] if payload.get('summary') else []), *selected]
    return [{**row, 'explicitReplyTarget': row['id'] == current.reply_to} for row in result]


async def capture_sources(db, actor, current, selected=None):
    store = await locked_store(db, actor, current.conversation_id)
    stamps = await manifest(db, actor, current.conversation_id)
    if selected is None:
        selected = store.payload.get('recentMessages', [])
        has_summary = bool(store.payload.get('summary'))
    else:
        has_summary = any(row['id'] == 'context-summary' for row in selected)
    summary_sources = store.payload.get('summarySources', {}) if has_summary else {}
    identifiers = {current.id, *summary_sources, *(row['id'] for row in selected)}
    check = AccessCheck(db, actor)
    sources = {identifier: stamp for identifier, stamp in stamps.items()
               if identifier in identifiers and not stamp['deleted']
               and stamp['createdAt'] <= current.created_at.isoformat() and await check.valid(stamp['access'])}
    return {'invalidationVersion': store.invalidation_version, 'summarySources': summary_sources,
            'through': {'messageId': current.id, 'createdAt': current.created_at.isoformat()},
            'sources': sources}


async def publish_summary(context, packet):
    from app.tasks.lease import lease
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        current = await owned(db, Message, job.target_id, actor)
        store = await locked_store(db, actor, current.conversation_id)
        stamps = await manifest(db, actor, current.conversation_id)
        expected = packet['sources']
        if store.invalidation_version != expected['invalidationVersion']:
            raise InputChanged(context=True)
        if store.payload.get('summaryThrough', {}).get('createdAt', '') > expected.get('through', {}).get('createdAt', ''):
            raise InputChanged(context=True)
        for identifier, stamp in expected['sources'].items():
            if identifier not in stamps or stamp['source'] != stamps[identifier]['source'] or not await valid(db, actor, stamps[identifier]['access']):
                raise InputChanged(context=True)
        dependencies = {'summaryAccess': packet.get('access', {}), 'summaryDependencies': packet.get('dependencies', {})}
        from app.security.versions import receipt_advanced_versions
        try:
            rebased = await receipt_advanced_versions(db, actor,
                dependencies['summaryDependencies'].get('business', {}), current.id)
        except Exception as error:
            from app.integrations.models.transport import ProviderError
            from fastapi import HTTPException
            if isinstance(error, (ProviderError, HTTPException)):
                raise InputChanged(context=True) from error
            raise
        dependencies['summaryDependencies'] = {**dependencies['summaryDependencies'], 'business': rebased}
        if not await summary_dependencies_valid(db, actor, dependencies):
            raise InputChanged(context=True)
        context.read_versions.update(rebased)
        if store.payload.get('compactionId') == packet['id']:
            if store.payload.get('summaryDependencies') != dependencies['summaryDependencies']:
                store.payload = {**store.payload, **dependencies}
                store.revision, store.updated_at = store.revision + 1, now()
            return
        # Rebase on the locked latest payload: later messages survive a delayed
        # publication. The source manifest, not creation-time alone, is the cursor.
        covered = {identifier: stamps[identifier] for identifier in packet['covered'] if identifier in stamps}
        older = store.payload.get('summarySources', {})
        if any(identifier not in covered for identifier in older):
            raise InputChanged(context=True)  # A newer summary cannot be overwritten by an older view.
        # Keep identifiers outside generated prose: summarization must not lose
        # the selected object or cache its mutable business content.
        referenced = (await db.execute(select(Message.id, Message.work_reference).where(
            Message.id.in_(covered), Message.owner_id == actor.id,
            Message.company_id == actor.company_id, Message.deleted.is_(False))
            .order_by(Message.created_at, Message.id))).all() if covered else []
        work_references = [{'messageId': row.id, 'workId': row.work_reference['workId']}
                           for row in referenced if row.work_reference]
        payload = {**store.payload, **dependencies, 'schemaVersion': SCHEMA, 'summary': packet['summary'], 'summaryThrough': expected.get('through', {}),
                   'summaryWorkReferences': work_references,
                   'summarySources': covered, 'sources': stamps, 'compactionId': packet['id'],
                   'recentMessages': [row for row in store.payload.get('recentMessages', []) if row['id'] not in covered]}
        store.payload, store.revision, store.updated_at = bounded(payload), store.revision + 1, now()


async def summary_dependencies_valid(db, actor, payload):
    """Tool-derived facts can outlive a failed job, but never its authorization."""
    if not await valid(db, actor, payload.get('summaryAccess', {}), latest=True):
        return False
    dependencies = payload.get('summaryDependencies', {})
    from app.security.versions import validate_cached_versions
    from app.integrations.models.transport import ProviderError
    from fastapi import HTTPException
    try:
        await validate_cached_versions(db, actor, dependencies.get('business', {}))
        from app.modules.attachments.models import Attachment
        for identifier, revision in dependencies.get('documents', {}).items():
            attachment = await owned(db, Attachment, identifier, actor)
            if attachment.extraction_revision != revision:
                return False
    except (HTTPException, ProviderError, KeyError, TypeError):
        return False
    return True
