"""Research-only progress: settle whole model batches, never the task budget."""
from app.core.digests import digest
from langchain_core.messages import AIMessage, ToolMessage

TOOLS = frozenset({'web_search', 'web_fetch'})
STOP_AFTER = 6
NOTICE = '连续检索未获得新证据，依据已有来源完成答复；仅说明影响本次请求的缺失信息。'


def journal(value):
    # Additive schema: old call decisions/receipts remain replayable. Counters
    # start with observed outcomes, never inferred from old incomplete records.
    return value.setdefault('research', {'batches': [], 'stalled': 0, 'stopped': False,
                                         'evidence': [], 'denied': {}})


def settle(value):
    research = journal(value)
    for batch in research['batches']:
        if batch.get('settled'):
            continue
        outcomes = list(batch['calls'].values())
        if any(outcome is None for outcome in outcomes):
            break
        # A sibling may finish after six failed requests in this same batch.
        # Its new evidence wins regardless of scheduling/completion order.
        research['stalled'] = 0 if any(outcomes) else research['stalled'] + len(outcomes)
        batch['settled'] = True
    research['stopped'] = research['stopped'] or research['stalled'] >= STOP_AFTER
    return research['stopped']


def register(value, call):
    research = journal(value)
    identifier = call.get('progressId', call['id'])
    batch_id = call.get('progressBatch', identifier)
    batch = next((item for item in research['batches'] if item['id'] == batch_id), None)
    if batch is None:
        settle(value)
        batch = {'id': batch_id, 'calls': dict.fromkeys(call.get('progressPeers') or [identifier])}
        research['batches'].append(batch)
    batch['calls'].setdefault(identifier, None)
    return research['stopped']


def complete(value, call, progress):
    research = journal(value)
    identifier = call.get('progressId', call['id'])
    batch_id = call.get('progressBatch', identifier)
    batch = next((item for item in research['batches'] if item['id'] == batch_id), None)
    if batch is not None and batch['calls'].get(identifier) is None:
        batch['calls'][identifier] = bool(progress)


def rejected_batch(value, messages):
    """Only a complete, entirely forbidden batch confirms a closed-tool loop."""
    index = next((index for index in range(len(messages) - 1, -1, -1)
                  if isinstance(messages[index], AIMessage)), None)
    if index is None:
        return False
    batch = messages[index]
    receipts = {message.tool_call_id for message in messages[index + 1:] if isinstance(message, ToolMessage)}
    records = value.get('research', {}).get('records', {})
    # Keep any valid sibling (including a cached page or a business operation)
    # open. Do not infer the completion of siblings that have not returned yet.
    return bool(batch.tool_calls) and all(
        call['id'] in receipts and records.get(digest({'message': batch.id, 'call': call['id']}), {}).get('decision') == 'research_stop'
        for call in batch.tool_calls)


def page_evidence(result):
    text = result.get('text')
    if not isinstance(text, str) or not text.strip():
        return None
    # Transport timestamps, cache hits and refreshed requests aren't new text.
    return digest({'url': result.get('url'), 'text': text})


def link_evidence(result):
    # A failed destination can still expose a real Location relation. This
    # records discovery, never upgrades that link into downloaded body text.
    return {digest({key: link.get(key) for key in ('url', 'title', 'discoveredOn', 'discoveryType')})
            for link in result.get('links', []) if isinstance(link, dict)
            and link.get('evidenceType') == 'page_link' and link.get('url') and link.get('discoveredOn')}


def has_snapshot(cache, url=None):
    from app.integrations.web_research import WebResearchError, public_url
    try:
        key = str(public_url(url)) if url is not None else None
    except (WebResearchError, TypeError):
        return False
    return any((key is None or address == key) and cache.clock() - at < cache.ttl
               for address, (at, _, _) in cache.pages.items())


def cached_read(context, call):
    return (call['name'] == 'web_fetch' and not call.get('args', {}).get('refresh')
            and has_snapshot(context.web_pages, call.get('args', {}).get('url')))


class SnapshotReader:
    """Read-only facade: expiration/eviction can never fall through to IO."""
    def __init__(self, cache):
        self.cache = cache

    async def get(self, key, download, *, refresh=False):
        from app.integrations.web_research import WebResearchError
        item = self.cache.pages.get(key)
        if refresh or item is None or self.cache.clock() - item[0] >= self.cache.ttl:
            raise WebResearchError('本轮已停止联网读取此页面，且没有可读取的正文快照。', code='research_stopped')
        return item[1], True
