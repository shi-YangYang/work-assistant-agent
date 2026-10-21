"""Task-local decisions; model assertions never become source or write authority.

The envelope travels on an existing tool call, not a routing-model call.
Only this module writes decisionFlow. The lease serializes parallel callbacks;
source identity is shared with the existing catalog/checkpoint input boundary.
"""
import copy
import json

from langchain_core.messages import ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from app.agent.runtime.tool_progress.evidence import failed_result, payload, recoverable_result, result_state
from app.agent.runtime import decision_effects
from app.tasks.context import input_scope_key as scope_key
from app.core.digests import digest

VERSION = 2
EXECUTION = frozenset({
    'execute_business_action', 'propose_progress', 'propose_followup',
    'generate_image', 'save_deliverable', 'save_memory', 'forget_memory',
    'export_table', 'create_chart', 'create_document', 'create_slides', 'run_python',
    'set_task_context', 'finish_task',
})
RECEIPTS = frozenset({'get_business_actions', 'read_execution'})
CONTROL = frozenset({'load_tools', 'request_user_input'})
RECORD_READS = frozenset({'find_work_items', 'get_work_item', 'list_work_updates',
    'find_team_members', 'query_team_business', 'query_reports', 'query_report_obligations',
    'read_team_source', 'get_message_context', 'read_deliverable'})
SOURCE_ARGUMENTS = frozenset({'attachment_id', 'attachment_ids', 'work_id', 'target_id',
    'report_id', 'deliverable_id', 'shared_attachment_ids', 'token', 'source_tokens', 'child_id'})
SOURCE_CONTAINERS = frozenset({'source', 'input_ref', 'input_refs', 'inputRefs', 'materials',
    'attachment', 'images', 'items'})
POLICY = '''调用随 _flow 给 route=fact（缺事实）/execute（执行）、need=具体事实缺口短句；scope=fact(默认)/full全文/link链接。缺用户选择直接 request_user_input；同批提问的独立事项用independent=true。内部字段不进正文。'''
REVIEW_POLICY = '''再次调用时复用 need 短句，给 resolved={已覆盖need:[实际receipt]}（无则{}）；目录/截断非全文。只为未覆盖事实继续读，已无缺口直接答或执行。after=实际receipt 配need用于失败恢复/写后相关读取。'''
SCHEMA = {'type': 'object', 'properties': {
    'route': {'type': 'string', 'enum': ['fact', 'execute']},
    'need': {'type': 'string', 'maxLength': 160},
    'ready': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 16},
    'resolved': {'type': 'object'},
    'scope': {'type': 'string', 'enum': ['fact', 'full', 'link']},
    'after': {'type': 'string'},
    'independent': {'type': 'boolean'},
}, 'additionalProperties': False}


def exploratory(name):
    return name not in EXECUTION | RECEIPTS | CONTROL


def schemas(tools, *, first=False, reviewing=False, tracking=False):
    """Decorate only offered schemas. Registered implementations stay unchanged."""
    result = []
    for tool in tools:
        schema = copy.deepcopy(convert_to_openai_tool(tool))
        name = schema['function']['name']
        if name not in RECEIPTS | {'request_user_input', 'set_task_context', 'finish_task'}:
            # POLICY defines this optional protocol once. Repeating its fields on
            # every tool costs input even when no tool is called; clean validates
            # the envelope before registered tools or authorization see it.
            parameters = schema['function']['parameters']
            required = ['need', 'resolved'] if reviewing and exploratory(name) else ['route', 'need'] if first or tracking and exploratory(name) else []
            parameters.setdefault('properties', {})['_flow'] = {'type': 'object', **({'required': required} if required else {})}
            if required:
                parameters['required'] = list(dict.fromkeys([*parameters.get('required', []), '_flow']))
        result.append(schema)
    return result


def clean(call):
    args = dict(call.get('args', {}))
    value = args.pop('_flow', None)
    valid = isinstance(value, dict) and not set(value) - set(SCHEMA['properties'])
    valid = valid and isinstance(value.get('need', ''), str) and len(value.get('need', '')) <= 160
    valid = valid and isinstance(value.get('after', ''), str) and len(value.get('after', '')) <= 80
    valid = valid and value.get('scope', 'fact') in ('fact', 'full', 'link')
    valid = valid and ('route' not in value or value['route'] in ('fact', 'execute'))
    valid = valid and ('route' not in value or bool(value.get('need', '').strip()) or 'resolved' in value)
    valid = valid and isinstance(value.get('independent', False), bool)
    ready = value.get('ready', []) if valid else []
    valid = valid and isinstance(ready, list) and len(ready) <= 16 and all(isinstance(item, str) and len(item) <= 80 for item in ready)
    resolved = value.get('resolved', {}) if valid else {}
    valid = valid and isinstance(resolved, dict) and len(resolved) <= 16
    valid = valid and all(isinstance(need, str) and need.strip() and len(need) <= 160
        and isinstance(receipts, list) and 0 < len(receipts) <= 16
        and all(isinstance(receipt, str) and 0 < len(receipt) <= 80 for receipt in receipts)
        for need, receipts in resolved.items())
    return {**call, 'args': args}, value if valid else {}


def current(context, job):
    scope = scope_key(context)
    saved = job.result.get('decisionFlow', {})
    if saved.get('version') == VERSION and saved.get('scope') == scope:
        value = copy.deepcopy(saved)
        value.setdefault('requirements', {})
        return value
    return {'version': VERSION, 'scope': scope, 'phase': 'exploring', 'calls': {}, 'evidence': [], 'pending': [], 'requirements': {}}


def save(job, value):
    if job.result.get('decisionFlow') != value:
        job.result = {**job.result, 'decisionFlow': value}


def identity(batch, call):
    return digest({'message': getattr(batch, 'id', None), 'call': call['id']})[:16]


def blocked(call, code):
    return ToolMessage(tool_call_id=call['id'], name=call['name'], status='error', content=json.dumps({
        'state': 'not_executed', 'executed': False, 'code': code,
        'message': {'question_pending': '先等待本次提问的答案；未执行事项仍属于原任务。',
                    'exploration_closed': '已有依据已进入交付阶段；继续必要执行或直接回答。',
                    'need_covered': '该事实已有有效依据；继续尚缺事实或直接交付。'}[code],
    }, ensure_ascii=False))


def source_versions(context, job=None, identifiers=None):
    result = getattr(job, 'result', {})
    return {'documents': context.document_versions, 'work': context.read_versions,
            'deliverables': context.deliverable_reads,
            'attachments': {item['id']: digest({'revision': item['revision'], 'sha256': item['sha256']})
                for item in result.get('sandboxSources', []) if item.get('kind') == 'attachment'
                and (identifiers is None or item['id'] in identifiers)},
            'business': {key: digest(item) for key, item in (getattr(job, 'access', None) or {}).get('reads', {}).items()
                if identifiers is None or key in identifiers}}


def sources(context, job, call, result):
    """Bind only this call's real reference fields, never unrelated task reads.

    Free-form document/body/code text is not scanned for IDs. A returned revision
    wins over a later context version, so an old receipt cannot become fresh.
    """
    identifiers, revisions = set(), {}

    def visit(value, *, returned=False):
        if isinstance(value, list):
            for item in value:
                visit(item, returned=returned)
        elif isinstance(value, dict):
            for key, item in value.items():
                if key in SOURCE_ARGUMENTS or returned and key in ('id', 'attachmentId', 'workId', 'objectId', 'deliverableId', 'token'):
                    identifiers.update(part for part in (item if isinstance(item, list) else [item]) if isinstance(part, str))
                elif key in SOURCE_CONTAINERS:
                    visit(item, returned=returned)
            identifier = value.get('id') if returned else None
            revision = value.get('extraction', {}).get('revision') if isinstance(value.get('extraction'), dict) else value.get('revision')
            if isinstance(identifier, str) and type(revision) is int:
                revisions[identifier] = revision
            if returned and isinstance(value.get('workId'), str) and type(value.get('workRevision')) is int:
                revisions[value['workId']] = value['workRevision']

    visit(call.get('args', {}))
    visit(result, returned=True)
    return {kind: {key: revisions.get(key, version) if kind in ('documents', 'work', 'deliverables') else version
                   for key, version in values.items() if key in identifiers}
            for kind, values in source_versions(context, job, identifiers).items()}


def supported(row, scope, context, job=None):
    if not row or row.get('outcome') != 'ok' or row.get('kind') in ('directory', 'unknown', 'control', 'reference'):
        return False
    identifiers = {key for values in row.get('sources', {}).values() for key in values}
    for name, current_versions in source_versions(context, job, identifiers).items():
        if any(current_versions.get(key) != version for key, version in row.get('sources', {}).get(name, {}).items()):
            return False
    if scope == 'full':
        return row.get('coverage') == 'complete'
    if scope == 'link':
        return row.get('kind') in ('link', 'text')
    return row.get('kind') != 'link' or row.get('hasSnippet') is True


def closed(value):
    return value['phase'] in ('executing', 'delivering', 'recovering', 'following')


def available(value, names):
    if not closed(value) or any(row.get('recovery') and not row.get('used') for row in value['calls'].values()):
        return names
    related = set().union(*(decision_effects.available(row) for row in value['calls'].values()))
    return names & (EXECUTION | RECEIPTS | CONTROL | related)


def policy(value):
    return POLICY + (REVIEW_POLICY if value['calls'] else '')


def notice(value):
    if not value['calls'] and value['phase'] == 'exploring':
        return ''
    # Pending requirements survive successful reads until the existing model
    # connects them to actual receipts. In-flight calls are a separate fact.
    missing = [need for need, row in value.get('requirements', {}).items() if not row.get('receipts')]
    covered = [need for need, row in value.get('requirements', {}).items() if row.get('receipts')]
    recover = [key for key, row in value['calls'].items() if row.get('recovery') and not row.get('used')]
    followups = {key: sorted(row['readScope']) for key, row in value['calls'].items() if row.get('readScope') and not row.get('used')}
    return '\n当前决策：' + json.dumps({'phase': value['phase'], 'missing': missing,
        **({'covered': covered} if covered else {}), **({'recovery': recover} if recover else {}),
        **({'changed': followups} if followups else {})}, ensure_ascii=False, separators=(',', ':'))


def refresh(context, job):
    """Invalidate only coverage whose original source revision changed."""
    value = current(context, job)
    invalid = False
    for row in value['requirements'].values():
        if row.get('receipts') and not all(supported(value['calls'].get(key), row['scope'], context, job) for key in row['receipts']):
            row.pop('receipts')
            invalid = True
    if invalid and value.get('closure') == 'requirements' and value['phase'] != 'waiting':
        value.update(phase='exploring', next='fact')
        value.pop('closure', None)
    if invalid:
        save(job, value)
    return value


def receive(context, job, batch):
    """Apply one existing model response before dispatching any parallel tools.

    A receipt can support a declared need; tool success alone never resolves it.
    New need text remains a model assertion, not server-certified relevance.
    Legacy/malformed metadata does not cause a repair round or authorize writes.
    """
    value = refresh(context, job)
    calls = getattr(batch, 'tool_calls', ())
    batch_key = digest({'message': getattr(batch, 'id', None), 'calls': calls})[:16]
    if value.get('modelBatch') == batch_key:
        return
    value['modelBatch'] = batch_key
    if not calls:
        if value['phase'] != 'waiting':
            value.update(phase='delivering', next='answer', reason='model_answer')
        save(job, value)
        return
    declarations = [(call, clean(call)[1]) for call in calls]
    missing = value['requirements']
    # Register every sibling need before applying coverage or deciding closure.
    # This prevents a satisfied A from suppressing the same batch's unresolved B.
    for call, flow in declarations:
        need = flow.get('need', '').strip()
        if exploratory(call['name']) and need:
            if need not in missing and len(missing) < 16:
                missing[need] = {'scope': flow.get('scope', 'fact')}
            elif need in missing and flow.get('scope') == 'full' and missing[need].get('scope') != 'full':
                # A stronger declared requirement invalidates weaker coverage;
                # siblings cannot downgrade it by resolving at default fact.
                missing[need] = {'scope': 'full'}
    reviewed = False
    for _, flow in declarations:
        for need, receipts in flow.get('resolved', {}).items():
            if need not in missing:
                continue
            scope = flow.get('scope', 'fact')
            required_scope = missing[need].get('scope', scope)
            if all(supported(value['calls'].get(key), scope, context, job) and supported(value['calls'].get(key), required_scope, context, job) for key in receipts):
                missing[need] = {'receipts': list(dict.fromkeys(receipts)), 'scope': 'full' if 'full' in (scope, required_scope) else required_scope}
                reviewed = True
    question = any(call['name'] == 'request_user_input' for call in calls)
    # Unannotated legacy reads cannot disappear behind a sibling's declaration.
    unknown_read = any(exploratory(call['name']) and (not flow or 'resolved' not in flow or
        flow.get('need', '').strip() not in missing and flow.get('need', '').strip()) for call, flow in declarations)
    pending_calls = any(not row.get('outcome') for row in value['calls'].values())
    if question:
        value['next'] = 'user_choice'
    elif reviewed and missing and all(row.get('receipts') for row in missing.values()) and not unknown_read and not pending_calls and value['phase'] == 'exploring':
        executing = any(call['name'] in EXECUTION for call in calls)
        value.update(phase='executing' if executing else 'delivering', next='execute' if executing else 'answer', closure='requirements')
    elif any(exploratory(call['name']) for call in calls):
        value['next'] = 'fact'
    else:
        value['next'] = 'execute'
    save(job, value)


def begin(context, job, call, batch, flow):
    value = current(context, job)
    key = identity(batch, call)
    prior = value['calls'].get(key)
    # Exact checkpoint replay must retain the original admit decision.
    if prior:
        return blocked(call, prior['blocked']) if prior.get('blocked') else None
    others = getattr(batch, 'tool_calls', ())
    question = any(item['name'] == 'request_user_input' for item in others)
    batch_key = digest({'message': getattr(batch, 'id', None), 'calls': [item['id'] for item in others]})[:16]
    # A dependency declaration only applies to this original parallel batch.
    # It cannot cross an older waiting gate or override explicit requires_step.
    if question and value['phase'] != 'waiting':
        value['questionBatch'] = batch_key
    independent = (question and flow.get('independent') is True and not call['args'].get('requires_step')
                   and value.get('questionBatch') == batch_key)
    code = None
    if call['name'] != 'request_user_input' and (question or value['phase'] == 'waiting') and not independent:
        code = 'question_pending'
    refreshing = call['name'] == 'get_work_item' and call['args'].get('work_id') in context.refresh_work_versions
    # The existing conflict gate permits exactly this source refresh. It does
    # not by itself change an open/closed decision or start unrelated recovery.
    recovering = False
    following = False
    recovery = value['calls'].get(flow.get('after', ''))
    if not code and closed(value) and exploratory(call['name']) and not refreshing:
        if flow.get('need', '').strip() and recovery and recovery.get('recovery') and not recovery.get('used'):
            value['phase'] = 'recovering'
            value['recoveryReceipt'] = flow['after']
            recovering = True
        elif flow.get('need', '').strip() and recovery and decision_effects.permits(recovery, call, getattr(job, 'access', None)):
            value['phase'] = 'following'
            value['followupReceipt'] = flow['after']
            following = True
        else:
            code = 'exploration_closed'
    if not code and not (refreshing or recovering or following) and exploratory(call['name']) and value['requirements'].get(flow.get('need', '').strip(), {}).get('receipts'):
        code = 'need_covered'
    if not code and flow.get('ready') and flow.get('route') != 'fact':
        pending = any(not row.get('outcome') and not row.get('blocked') for row in value['calls'].values())
        pending = pending or any(item['id'] != call['id'] and exploratory(item['name']) for item in others)
        if not pending and not exploratory(call['name']) and all(supported(value['calls'].get(item), flow.get('scope', 'fact'), context, job) for item in flow['ready']):
            value.update(evidence=list(dict.fromkeys(flow['ready'])))
            if value['phase'] != 'waiting':
                value['phase'] = 'executing'
        # Optional readiness controls exploration only. Invalid hints must not
        # block an otherwise valid operation or demand unnecessary source reads.
    if not code and call['name'] in EXECUTION and value.get('recoveryReceipt'):
        value['calls'][value.pop('recoveryReceipt')]['used'] = True
        if value['phase'] == 'recovering':
            value['phase'] = 'executing'
    if not code and call['name'] in EXECUTION and value.get('followupReceipt'):
        value['calls'][value.pop('followupReceipt')]['used'] = True
        if value['phase'] == 'following':
            value['phase'] = 'executing'
    need = flow.get('need', '').strip()
    if not code and exploratory(call['name']) and need and need not in value['requirements'] and len(value['requirements']) < 16:
        value['requirements'][need] = {'scope': flow.get('scope', 'fact')}
    value['calls'][key] = {'tool': call['name'], 'need': need,
                          'route': 'user_choice' if call['name'] == 'request_user_input' else flow.get('route', 'unknown'),
                          **({'recovering': True} if recovering and not code else {}),
                          **({'following': flow['after']} if following and not code else {}),
                          **({'independent': True} if independent and not code else {}),
                          **({'blocked': code, 'outcome': 'not_executed'} if code else {})}
    if code:
        value['pending'] = list(dict.fromkeys([*value['pending'], call['name']]))
    save(job, value)
    return blocked(call, code) if code else None

def facts(call, result, message):
    """Only transport/source facts. Never infer task sufficiency from success."""
    state = result_state(result)
    failed = message.status == 'error' or failed_result(result)
    row = {'outcome': 'failed' if failed else 'waiting' if state in ('queued', 'pending', 'running', 'waiting', 'awaiting_confirmation', 'awaiting_input') else 'ok',
           'kind': 'unknown', 'coverage': 'unknown'}
    if failed:
        row['recovery'] = recoverable_result(result)
        return row
    name, args = call['name'], call.get('args', {})
    if name in CONTROL | {'set_task_context', 'finish_task'}:
        row['kind'] = 'control'
    elif name in EXECUTION and state in ('succeeded', 'completed', 'partial'):
        row['kind'] = 'receipt'
    elif name in RECEIPTS:
        # Receipt directories do not prove that any particular action finished.
        row['kind'] = 'receipt' if result.get('evidenceType') == 'execution_receipt' else 'directory'
    elif name == 'web_search':
        row.update(kind='link', coverage='partial', hasSnippet=any(item.get('snippet') for item in result.get('items', [])))
    elif name == 'web_fetch':
        row.update(kind='text' if result.get('evidenceType') == 'page_text' and result.get('text') else 'link',
                   coverage='partial' if result.get('truncated', True) else 'complete')
    elif ((name == 'find_documents' and not args.get('attachment_id')) or
          (name == 'read_images' and (not args.get('attachment_ids') or state in ('listed', 'document_pages'))) or
          name == 'list_work_materials' or name == 'read_deliverable' and not args.get('deliverable_id')):
        row['kind'] = 'directory'
    elif 'pageRefs' in result:
        # Preparing private image references is not proof that the following
        # model request actually received pixels (it can reject/degrade them).
        row.update(kind='directory', coverage='partial')
    elif isinstance(result.get('readScope'), dict):
        scope = result['readScope']
        full = result.get('sourceComplete') is True and (scope.get('allExtractedTextReturned') is True or
            scope.get('extractedChunks', 0) > 0 and scope.get('returnedChunksThisTask', 0) >= scope['extractedChunks'])
        full = full and not scope.get('limitations') and not set(scope.get('limitationsCodes', ())) - {'unreturned_text'}
        row.update(kind='text', coverage='complete' if full else 'partial')
    elif name == 'read_images' and isinstance(result.get('images'), list) and result['images'] and all(isinstance(item, dict) for item in result['images']) and result.get('text'):
        # complete describes pixels supplied to the auxiliary vision model, not
        # exhaustive text returned by its question-specific answer.
        row.update(kind='text', coverage='partial')
    elif result.get('kind') in ('audio', 'image') and result.get('attachmentId') and result.get('text'):
        # Transcription and a visual answer are facts, not complete raw audio or
        # an exhaustive transcription of everything visible in the source.
        row.update(kind='text', coverage='partial')
    elif name == 'inspect_table' and state == 'succeeded' and isinstance(result.get('data'), dict):
        row.update(kind='records', coverage='partial')
    elif name in RECORD_READS and any(key in result for key in ('items', 'id', 'workId', 'messageId', 'objectId')):
        # Structured business data are facts, but not proof of reading attachments.
        row.update(kind='records', coverage='partial')
    elif name == 'read_file':
        row['kind'] = 'reference'
    if state == 'partial' or result.get('scopeWarning') or result.get('rangeError') or result.get('contentTruncated'):
        row['coverage'] = 'partial'
    return row


def end(context, job, call, message):
    result = payload(message)
    key = call.get('decisionId')
    value = current(context, job)
    prior = value['calls'].get(key, {'tool': call['name'], 'need': ''})
    if not prior.get('outcome'):
        prior = {**prior, **facts(call, result, message),
                 'result': digest(result),
                 'sources': sources(context, job, call, result)}
        if prior['outcome'] == 'ok':
            changes = decision_effects.capture(call, result, value['calls'])
            if changes:
                prior.update(changes=changes, readScope=decision_effects.scope(changes))
            if prior.get('following'):
                decision_effects.extend(value['calls'][prior['following']], call, result, getattr(job, 'access', None))
        value['calls'][key] = prior
        if result.get('interactionId') and result.get('state') in ('waiting', 'clarification'):
            value.update(phase='waiting', interactionId=result['interactionId'])
        # A recovery may need directory -> body -> next page. Keep the same
        # failure-scoped episode until execution resumes; each read still needs
        # after/need and passes existing dedup/no-progress/budget controls.
        save(job, value)
    # Legacy terminal receipts have a strict Delivery schema and return_direct.
    # Their successful output must remain byte-for-byte parseable on replay.
    if call['name'] == 'finish_task':
        return message
    if isinstance(message.content, str):
        try:
            raw = json.loads(message.content)
        except (ValueError, TypeError):
            return message
        if isinstance(raw, dict):
            return message.model_copy(update={'content': json.dumps({**raw, '_flow': {
                'receipt': key, 'outcome': prior['outcome'], 'kind': prior['kind'], 'coverage': prior['coverage'],
            }}, ensure_ascii=False)})
    return message


def finish(context, job):
    """Direct prose ends the graph, not a semantic proof of completeness."""
    value = current(context, job)
    if value['phase'] != 'waiting':
        for row in value['calls'].values():
            if row.get('changes'):
                row['used'] = True
        value.pop('followupReceipt', None)
        value.update(phase='delivering', reason='model_answer')
        save(job, value)
