"""Deletion under the same owner lock used by API writes and harness checkpoints.

Tombstones retain identity/version only. Source cleanup is durable and retryable;
confirmed business snapshots are deliberately not recursively removed.
"""
from sqlalchemy import delete, select, text
from .models import DocumentChunk, Attachment, Conversation, Idempotency, Job, Member, Message, ProgressDraft, Report, ReportRevision, WorkItem, WorkRevision, now
from .service import problem, version


async def target(db, model, identifier, actor, expected):
    query = select(model).where(model.id == identifier, model.company_id == actor.company_id)
    if model is not Report or actor.role != 'admin':
        query = query.where(model.owner_id == actor.id)
    else:
        query = query.where(model.owner_id.in_(select(Member.id).where(Member.company_id == actor.company_id, Member.role == 'employee')))
    owner = await db.scalar(query.with_only_columns(model.owner_id))
    if not owner:
        problem(404, '记录不存在或无权管理')
    await db.scalar(select(Member).where(Member.id == owner).with_for_update())
    item = await db.scalar(query.with_for_update().execution_options(populate_existing=True))
    if not item.deleted:
        version(item, expected)
    return item


async def invalidate_context(db, owner_id, company_id, target_ids, *, sources_changed=False):
    # A queued unrelated task has captured no chat context and must stay queued.
    # In-flight tools may have read a shared source; fence those only when actual
    # business inputs changed. Other jobs keep their generation snapshots.
    query = select(Job).where(Job.owner_id == owner_id)
    predicate = Job.target_id.in_(target_ids)
    if sources_changed:
        predicate = predicate | (Job.state == 'running')
    jobs = (await db.scalars(query.where(predicate).with_for_update())).all()
    for job in jobs:
        if job.state in ('queued', 'running', 'failed', 'awaiting_retry'):
            job.state, job.phase, job.error = 'cancelled', 'deleted_context', '相关资料已删除，本次处理已停止'
            job.fence += 1
            job.lease_until = None
        job.result = {}
    # Source text can occur in completed contexts too. Purging those caches is
    # safe; queued unrelated jobs and their immutable input snapshots stay intact.
    prefixes = [f'{company_id}:{owner_id}:job:%'] if sources_changed else [f'{company_id}:{owner_id}:job:{job.id}%' for job in jobs]
    for table in ('checkpoint_writes', 'checkpoint_blobs', 'checkpoints'):
        if prefixes and await db.scalar(text('SELECT to_regclass(:table)'), {'table': table}):
            for prefix in prefixes:
                await db.execute(text(f'DELETE FROM {table} WHERE thread_id LIKE :prefix'), {'prefix': prefix})


async def purge_messages(db, ids):
    if not ids:
        return
    messages = (await db.scalars(select(Message).where(Message.id.in_(ids)).with_for_update())).all()
    for message in messages:
        message.deleted = True
        message.text = message.reply = message.transcript = ''
        message.suggestions = message.transcript_history = message.citations = []
        message.reply_to = None
        message.transcript_revision += 1
    replies = (await db.scalars(select(Message).where(Message.reply_to.in_(ids)))).all()
    for reply in replies:
        reply.reply_to = None
    drafts = (await db.scalars(select(ProgressDraft).where(ProgressDraft.message_id.in_(ids)))).all()
    for draft in drafts:
        draft.status, draft.content = 'deleted', {}
        draft.revision += 1
    attachments = (await db.scalars(select(Attachment).where(Attachment.message_id.in_(ids)))).all()
    for item in attachments:
        item.deleted, item.name, item.sha256 = True, '', ''
        item.extraction_status, item.extraction_info, item.parser_version = 'deleted', {}, ''
        item.extraction_revision += 1
        await db.execute(delete(DocumentChunk).where(DocumentChunk.attachment_id == item.id))
        await invalidate_context(db, item.owner_id, item.company_id, {item.id})
    attachment_ids = {item.id for item in attachments}
    if attachment_ids:
        owners = {item.owner_id for item in attachments}
        jobs = (await db.scalars(select(Job).where(Job.owner_id.in_(owners), Job.kind == 'message'))).all()
        dependent_ids = {job.target_id for job in jobs if any(evidence[0] in attachment_ids for evidence in job.result.get('documentReads', {}).values())}
        others = (await db.scalars(select(Message).where(Message.owner_id.in_(owners), Message.deleted.is_(False)))).all()
        for other in others:
            if other.id not in dependent_ids and not any(citation.get('attachmentId') in attachment_ids for citation in other.citations):
                continue
            # An assistant reply may quote extracted text even without a citation.
            # Purge dependent generated caches, retaining user text and confirmed
            # Work/Report revisions. Pending suggestions are not confirmed facts.
            other.reply, other.citations = '', []
            drafts = (await db.scalars(select(ProgressDraft).where(ProgressDraft.message_id == other.id, ProgressDraft.status == 'pending'))).all()
            for draft in drafts:
                draft.status, draft.content = 'deleted', {}
                draft.revision += 1
            pending = {draft.id for draft in drafts}
            other.suggestions = [suggestion for suggestion in other.suggestions if suggestion['id'] not in pending]
            await invalidate_context(db, other.owner_id, other.company_id, {other.id})


async def remove_report(db, item, actor):
    if actor.role != 'admin' and item.published_revision:
        problem(403, '已提交的报告不能删除')
    if item.deleted:
        return
    revisions = (await db.scalars(select(ReportRevision).where(ReportRevision.report_id == item.id))).all()
    source_ids = set(item.source_ids) | set((item.candidate or {}).get('sourceIds', []))
    for revision in revisions:
        source_ids.update(revision.source_ids)
    sources = (await db.scalars(select(WorkRevision).where(WorkRevision.id.in_(source_ids), WorkRevision.owner_id == item.owner_id, WorkRevision.company_id == item.company_id))).all()
    message_ids = {identifier for source in sources for identifier in source.source_ids}
    if actor.role == 'admin':
        # JSON references are still checked against actual ownership before purge.
        actual = (await db.scalars(select(Message.id).where(Message.id.in_(message_ids), Message.owner_id == item.owner_id, Message.company_id == item.company_id))).all()
        await purge_messages(db, actual)
    # Consume documentReads before invalidation clears running job results.
    # The owner lock fences tools/checkpoints until this transaction commits.
    await invalidate_context(db, item.owner_id, item.company_id, {item.id, *(message_ids if actor.role == 'admin' else [])}, sources_changed=actor.role == 'admin' and bool(message_ids))
    item.deleted, item.content, item.candidate, item.source_ids = True, {}, None, []
    item.revision += 1
    await db.execute(delete(ReportRevision).where(ReportRevision.report_id == item.id))
    await db.execute(delete(Idempotency).where(Idempotency.owner_id == item.owner_id, ((Idempotency.action == f'submit:{item.id}') | ((Idempotency.action == 'generate-report') & (Idempotency.response['reportId'].astext == item.id)))))


async def remove_work(db, item):
    if item.deleted:
        return
    revisions = set((await db.scalars(select(WorkRevision.id).where(WorkRevision.work_id == item.id))).all())
    report_jobs = (await db.scalars(select(Job).where(Job.owner_id == item.owner_id, Job.kind == 'report', Job.state.in_(['queued', 'failed', 'awaiting_retry'])))).all()
    affected_reports = {job.target_id for job in report_jobs if revisions.intersection(job.result.get('sourceIds', []))}
    await invalidate_context(db, item.owner_id, item.company_id, {item.id, *affected_reports}, sources_changed=True)
    item.deleted, item.title, item.content = True, '', {}
    item.revision += 1
    # Keep revisions referenced by reports; they are confirmed business facts.
    drafts = (await db.scalars(select(ProgressDraft).where(ProgressDraft.work_id == item.id, ProgressDraft.status == 'pending'))).all()
    for draft in drafts:
        draft.status, draft.content = 'deleted', {}
        draft.revision += 1


async def conversation_impact(db, item):
    messages = set((await db.scalars(select(Message.id).where(Message.conversation_id == item.id, Message.deleted.is_(False)))).all())
    revisions = (await db.scalars(select(WorkRevision).where(WorkRevision.owner_id == item.owner_id, WorkRevision.company_id == item.company_id))).all()
    retained = messages.intersection(identifier for revision in revisions for identifier in revision.source_ids)
    return messages, retained


async def remove_conversation(db, item):
    if item.deleted:
        return
    messages, retained = await conversation_impact(db, item)
    await purge_messages(db, messages - retained)
    # Retained business-source messages may still have generated replies or
    # suggestions depending on a discarded document from this conversation.
    await invalidate_context(db, item.owner_id, item.company_id, messages, sources_changed=bool(messages - retained))
    drafts = (await db.scalars(select(ProgressDraft).where(ProgressDraft.message_id.in_(messages), ProgressDraft.status == 'pending'))).all()
    for draft in drafts:
        draft.status, draft.content = 'deleted', {}
        draft.revision += 1
    item.deleted, item.title, item.updated_at = True, '', now()
    item.revision += 1


async def clean_files(db, settings, owner_id=None):
    query = select(Attachment).where(Attachment.deleted.is_(True))
    if owner_id:
        query = query.where(Attachment.owner_id == owner_id)
    items = (await db.scalars(query)).all()
    for item in items:
        (settings.media_dir / item.id).unlink(missing_ok=True)
    return len(items)
