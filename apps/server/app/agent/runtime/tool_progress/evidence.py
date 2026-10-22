"""Tool-result adapters keep raw data out of the durable progress journal."""
import json
from dataclasses import asdict
from app.core.digests import digest
from app.agent.tool_results import failed_result, recoverable_result, result_state

WRITES = frozenset({'generate_image', 'execute_business_action', 'propose_progress', 'propose_followup', 'save_memory', 'forget_memory', 'save_deliverable', 'request_user_input'})
CURSORS = {'read_images': 'start', 'read_document': 'start', 'find_documents': 'start', 'read_deliverable': 'offset',
           'find_work_items': 'cursor', 'get_work_item': 'body_start',
           'list_work_updates': 'start', 'list_work_materials': 'start', 'read_work_material': 'start',
           'find_team_members': 'cursor', 'query_team_business': 'cursor', 'read_team_source': 'start',
           'query_reports': 'cursor', 'query_report_obligations': 'cursor', 'web_fetch': 'offset', 'read_execution': 'offset'}


def payload(message):
    try:
        result = json.loads(message.content)
        return result if isinstance(result, dict) else {'value': result}
    except (ValueError, TypeError, AttributeError):
        return {'text': str(getattr(message, 'content', message))}


def dependencies(context, job, call=None):
    memory = asdict(context.memory_snapshot) if context.memory_snapshot else None
    if call and call['name'] in WRITES:
        if call['name'] in ('save_memory', 'forget_memory'):
            return digest({'memory': memory})
        def references(value):
            if isinstance(value, dict):
                return set().union(*(references(item) for item in value.values())) if value else set()
            if isinstance(value, list):
                return set().union(*(references(item) for item in value)) if value else set()
            return {value} if isinstance(value, str) else set()
        ids = references(call.get('args', {}))
        return digest({'reads': {key: version for key, version in context.read_versions.items() if key in ids},
                       'deliverables': {key: version for key, version in context.deliverable_reads.items() if key in ids},
                       'documents': {key: version for key, version in context.document_versions.items() if key in ids}})
    return digest({'reads': context.read_versions, 'documents': context.document_versions,
        'documentReads': context.document_reads, 'deliverables': context.deliverable_reads,
        'memory': memory, 'sources': job.result.get('sandboxSources', []),
        'contextVersion': context.context_sources.get('invalidationVersion')})


def request_key(call):
    args = dict(call.get('args', {}))
    if call['name'] == 'web_fetch':
        args = {'offset': 0, 'find': '', 'match_index': 0, **args}
        args.pop('refresh', None)
        if isinstance(args.get('url'), str):
            args['url'] = args['url'].partition('#')[0]
    elif call['name'] == 'web_search':
        if isinstance(args.get('query'), str):
            args['query'] = ' '.join(args['query'].split())
        domains = args.get('domains')
        if domains is None or isinstance(domains, list) and all(isinstance(domain, str) for domain in domains):
            args['domains'] = sorted(domains or [])
    return digest({'name': call['name'], 'args': args})


def search_evidence(result):
    """Query wording/ranking aren't information; changed snippets and new URLs are."""
    return sorted({digest({key: item.get(key) for key in ('url', 'title', 'snippet')})
                   for item in result.get('items', []) if isinstance(item, dict) and item.get('url')})


def reusable_read(call, result):
    if call['name'] in ('web_search', 'find_documents'):
        return not failed_result(result)
    if call['name'] == 'web_fetch':
        return (not failed_result(result) or result.get('errorCode') in ('http_401', 'http_403', 'http_404', 'http_410', 'blocked_url', 'web_challenge')
                or result.get('errorCode') == 'web_network' and result.get('attemptsExhausted') is True)
    return False


def terminal_web_failure(result):
    return (result.get('errorCode') in ('http_401', 'http_403', 'http_404', 'http_410', 'blocked_url', 'web_challenge')
            or result.get('errorCode') == 'web_network' and result.get('attemptsExhausted') is True)


def web_address(call):
    url = call.get('args', {}).get('url')
    if call['name'] != 'web_fetch' or not isinstance(url, str) or not url:
        return None
    from app.integrations.web_research import WebResearchError, public_url
    try:
        parsed = public_url(url)
        # Canonicalize a missing root slash without decoding an encoded path.
        url = str(parsed.copy_with(path='/') if parsed.raw_path.partition(b'?')[0] in (b'', b'/') else parsed)
    except WebResearchError:
        url = url.partition('#')[0]
    return digest(url)


def exploratory_result(journal, call, result, identifier, deps):
    """Different queries / first unavailable addresses are soft, not new facts."""
    search = call['name'] == 'web_search' and not failed_result(result)
    code = result.get('errorCode', '')
    unavailable = call['name'] == 'web_fetch' and result.get('state') == 'unavailable' and (
        code in ('web_network', 'web_challenge') or isinstance(code, str) and code.startswith('http_'))
    if not search and not unavailable:
        return False
    previous = [row for row in journal['calls'] if row['id'] != identifier
                and row.get('result') and row.get('executed') is not False and row['dependencies'] == deps]
    request = request_key(call)
    if search:
        return not any(row['request'] == request for row in previous)
    address = web_address(call)
    return bool(address and not any(row.get('address', row.get('deniedAddress')) == address
                or row['request'] == request for row in previous))


def result_key(call, result):
    # Drop only transport metadata, not content, locations or source versions.
    value = {key: item for key, item in result.items() if key not in ('timestamp', 'updatedAt', 'createdAt', 'callId', 'toolCallId', 'fetchedAt', 'cacheHit')}
    args = call.get('args', {})
    if call['name'] == 'web_search' and not failed_result(value):
        return digest({'name': call['name'], 'evidence': search_evidence(value)})
    if call['name'] == 'web_fetch' and not failed_result(value):
        # The returned excerpt/match positions prove coverage. Refresh flags and
        # guessed offsets do not; equivalent requests share one result identity.
        args = {}
    if value.get('fieldIssues'):
        value = {'category': value.get('category'), 'fieldIssues': [{key: item.get(key) for key in ('field', 'code')} for item in value['fieldIssues']]}
        args = {key: args.get(key) for key in ('action', 'target_id', 'expected_revision')}
    elif failed_result(value):
        value.pop('message', None)
        value.pop('nextStep', None)
        value.pop('progressNotice', None)
    elif call['name'] == 'execute_business_action' and result.get('id') and result.get('state') in ('succeeded', 'pending', 'running'):
        value = {key: result.get(key) for key in ('id', 'state', 'objectId', 'objectRevision', 'revision', 'job')}
        args = {}
    elif call['name'] == 'generate_image' and result.get('operationId'):
        value = {key: result.get(key) for key in ('state', 'operationId')}
        args = {}
    elif call['name'] == 'generate_image' and isinstance(result.get('results'), list):
        value = {'state': result.get('state'), 'notExecutedCount': result.get('notExecutedCount'),
                 'results': [{key: item.get(key) for key in ('state', 'operationId', 'code')} for item in result['results']]}
        args = {}
    elif call['name'] in ('save_memory', 'forget_memory') and result.get('state') == 'succeeded':
        value = {key: result.get(key) for key in ('state', 'revision', 'generation', 'operation')}
        args = {}
    return digest({'name': call['name'], 'args': args, 'result': value})


def page_cursor(call):
    if call['name'] == 'web_fetch' and call.get('args', {}).get('find'):
        return 'match_index'
    return CURSORS.get(call['name'])


def page_scope(call):
    cursor = page_cursor(call)
    args = call.get('args', {})
    if not cursor:
        return None
    excluded = {cursor}
    if call['name'] == 'web_fetch':
        excluded.update(('refresh', 'offset', 'match_index'))
        args = {**args, 'find': args.get('find', '')}
    return digest({'name': call['name'], 'args': {key: value for key, value in args.items() if key not in excluded}})


def completed_page(call, result):
    terminal = ('nextMatchIndex',) if call['name'] == 'web_fetch' and call.get('args', {}).get('find') else ('nextCursor', 'nextOffset', 'nextBodyStart')
    if any(name in result and result[name] is None for name in terminal):
        return page_scope(call)
    return None
