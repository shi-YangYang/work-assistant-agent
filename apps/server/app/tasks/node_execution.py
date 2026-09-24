"""Opt-in assistant adapter: durable attempts, authorization and result recovery."""
import asyncio
import contextvars
import json
import random
import time
from app.core.digests import digest
from app.tasks.context import BudgetExceeded, LostLease
from app.tasks.lease import lease
from app.tasks.node_failures import classify
from app.tasks.node_state import MAX_NODES, MAX_OUTPUT_BYTES, execution, save
from app.tasks.retry import Attempt, Failure, NodeFailed, run

active_node = contextvars.ContextVar('assistant_node', default=None)


async def initialize(context, input_key):
    if not context.node_retry:
        return
    scope = digest({'input': input_key, 'config': context.model_binding, 'configAttempt': context.config_attempt})
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        state = execution(job)
        if state.get('scope') != scope:
            # Changed input starts a new graph. Retain bounded summaries only;
            # prior raw results must not become a second source of business truth.
            for row in state.get('nodes', []):
                row.pop('output', None)
            state = {'scope': scope, 'nodes': state.get('nodes', [])[-32:]}
        state.setdefault('deadline', time.time() + 420)
        state.setdefault('nodes', [])
        save(job, state)
        context.node_scope, context.node_deadline = scope, state['deadline']
        context.read_versions.update(state.get('readVersions', {}))
        context.calls = state.get('actualCalls', 0)
        context.input_tokens = state.get('inputTokens', 0)
        context.output_tokens = state.get('outputTokens', 0)


async def validate_config(db, context):
    if (context.model_binding or {}).get('assistant'):
        from app.modules.model_services.bindings import resolve_bound
        await resolve_bound(db, context.settings, context.company_id, context.model_binding, 'assistant')


async def validate_cached_versions(db, actor, versions):
    from app.modules.work.models import WorkItem
    from app.modules.reports.models import Report
    from app.security.ownership import owned
    from app.security.access import require
    from app.integrations.models.transport import ProviderError
    for identifier, revision in versions.items():
        model = WorkItem if await db.get(WorkItem, identifier) else Report
        record = await owned(db, model, identifier, actor, read=True)
        if model == WorkItem:
            await require(db, actor, record.access, retained=True)
        if record.revision != revision:
            raise ProviderError('version_conflict', '已读取的工作或报告已变化，请重新提问以读取最新内容')


async def check(context):
    async with context.sessions() as db:
        _, actor = await lease(db, context)
        await validate_config(db, context)
        await validate_cached_versions(db, actor, context.read_versions)
    if time.time() >= context.node_deadline:
        raise BudgetExceeded('本次处理已达到时间限制，已停止；可重试此步骤')


async def recover_receipt(db, context, job, actor, row):
    from app.modules.operations.models import BusinessAction
    from app.modules.operations.receipts import action_dto
    from app.security.ownership import owned
    from app.integrations.models.transport import ProviderError
    receipt = await owned(db, BusinessAction, row['receiptId'], actor)
    if receipt.message_id != job.target_id:
        raise ProviderError('version_conflict', '操作来源已变化，请重新提问')
    result = await action_dto(db, actor, receipt)
    versions = dict(context.read_versions)
    identifier, revision = result.get('objectId'), result.get('objectRevision')
    if identifier and revision:
        versions[identifier] = revision
    elif result['state'] in ('unavailable', 'conflict'):
        raise ProviderError('version_conflict', '操作关联资料已变化或无权查看，请重新提问')
    await validate_cached_versions(db, actor, versions)
    # Only the exact version authenticated by this node's own receipt can
    # replace a stale read. A later external edit/deletion still fails above.
    context.read_versions.update(versions)
    return result


async def execute_node(context, *, identity, kind, label, operation, encode=lambda x: x,
                       decode=lambda x: x, outcome=None, safe_replay=True, restore=None,
                       receipt_output=lambda x: x):
    if not context.node_retry:
        return await operation()
    parent = active_node.get()
    identifier = digest({'scope': context.node_scope, 'parent': parent[0] if parent else None, 'kind': kind, 'identity': identity})
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        await validate_config(db, context)
        state = execution(job)
        row = next((item for item in state['nodes'] if item['id'] == identifier), None)
        if row is None:
            active = [item for item in state['nodes'] if item['scope'] == context.node_scope]
            count = sum(item['kind'] == kind for item in active)
            if len(state['nodes']) >= MAX_NODES or kind == 'tool' and count >= 16 or kind != 'tool' and sum(item['kind'] != 'tool' for item in active) >= 8:
                raise BudgetExceeded('本次处理步骤已达到限制，请补充说明后继续')
            row = {'id': identifier, 'scope': context.node_scope, 'kind': kind, 'label': label,
                   'parentId': parent[0] if parent else None, 'state': 'waiting', 'attempts': 0,
                   'round': job.attempt, 'totalRetries': 0, 'resumable': True}
            state['nodes'].append(row)
            save(job, state)
        if 'output' in row and not row.get('receiptId'):
            # Lease rechecks source permissions and revisions before cached data
            # can reach the model, just as it does for graph checkpoint restores.
            if restore:
                return decode(await restore(db, actor, row['output']))
            await validate_cached_versions(db, actor, row.get('readVersions', {}))
            context.read_versions.update(state.get('readVersions', {}))
            return decode(row['output'])
        if row['state'] in ('failed', 'cancelled') and not row.get('receiptId'):
            raise NodeFailed(Failure(row.get('errorCode', 'failed'), row.get('error', '此步骤未完成')), identifier)
        attempt = Attempt(row['attempts'], row.get('nextAt'))
        if row['state'] == 'running':
            if not safe_replay and not row.get('receiptId'):
                raise NodeFailed(Failure('uncertain', '上次操作结果未知，请核对业务记录后再处理'), identifier)
            # An interrupted request consumes its attempt. Never reset to zero
            # on a lease/fence change. Receipts are recovered before retrying.
            attempt.next_at = time.time() + 1
    token = active_node.set((identifier, kind))

    async def recover():
        async with context.sessions.begin() as db:
            job, actor = await lease(db, context)
            await validate_config(db, context)
            row = next(item for item in execution(job)['nodes'] if item['id'] == identifier)
            if not row.get('receiptId'):
                return False, None
            return True, receipt_output(await recover_receipt(db, context, job, actor, row))

    async def emit(status, current, failure):
        async with context.sessions.begin() as db:
            job, _ = await lease(db, context)
            state = execution(job)
            row = next(item for item in state['nodes'] if item['id'] == identifier)
            row['totalRetries'] += max(0, current.count - max(1, row['attempts']))
            row.update(state=status, attempts=current.count, nextAt=current.next_at,
                       errorCode=failure.code if failure else '', error=failure.message[:240] if failure else '')
            save(job, state)

    try:
        result = await run(operation, classify=classify, before=lambda: check(context), emit=emit,
                           attempt=attempt, deadline=context.node_deadline, jitter=lambda: random.uniform(0, .2),
                           recover=recover if kind == 'tool' else None)
        encoded = encode(result)
        status, detail = outcome(result) if outcome else ('succeeded', '')
        async with context.sessions.begin() as db:
            job, _ = await lease(db, context)
            state = execution(job)
            row = next(item for item in state['nodes'] if item['id'] == identifier)
            row.update(state=status, nextAt=None, error=detail[:240], errorCode='business' if detail else '', resumable=False)
            # Normalized graph messages / validated verdicts only; no request
            # arguments, credentials, provider wire response or reasoning fields.
            row['output'] = encoded
            row['readVersions'] = dict(context.read_versions)
            if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_OUTPUT_BYTES:
                row.pop('output')
                row.update(state='failed', error='恢复数据超过本次限制，请缩小处理范围', errorCode='budget', resumable=False)
                save(job, state)
                raise BudgetExceeded('恢复数据超过本次限制，请缩小处理范围')
            state['readVersions'] = context.read_versions
            save(job, state)
        return result
    except NodeFailed as error:
        if not error.node_id:
            error.node_id = identifier
        raise
    except (Exception, asyncio.CancelledError) as error:
        try:
            failure = classify(error)
            await emit('cancelled' if failure.cancelled else 'failed', attempt, failure)
        except LostLease:
            pass
        raise
    finally:
        active_node.reset(token)
