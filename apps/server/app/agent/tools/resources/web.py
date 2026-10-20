import json
from urllib.parse import urlsplit
from langchain.tools import ToolRuntime, tool
from app.integrations import web_research
from app.tasks.context import RunContext
from app.tasks.lease import lease


def public_address(value):
    try:
        return str(web_research.public_url(value))
    except (web_research.WebResearchError, TypeError):
        return None


def redirect_links(links):
    result = []
    for item in links or []:
        if not isinstance(item, dict) or item.get('discoveryType') != 'http_redirect':
            continue
        target, origin = public_address(item.get('url')), public_address(item.get('discoveredOn'))
        if target and origin:
            link = {'url': target, 'title': urlsplit(target).hostname, 'evidenceType': 'page_link',
                    'discoveryType': 'http_redirect', 'discoveredOn': origin, 'fetchState': 'not_read'}
            if link not in result:
                result.append(link)
    return result


async def unavailable(context, value, message, *, is_fetch=False, code='unavailable', attempts_exhausted=False, category='', links=None, failed_url=None):
    if code == 'web_network' and attempts_exhausted:
        message = message.removesuffix('，请稍后再试') + '；本次自动尝试已结束'
    elif is_fetch and code in ('http_401', 'http_403'):
        message = f'本次网页正文读取被网站拒绝（HTTP {code[5:]}）'
    result = {'state': 'unavailable', 'errorCode': code, 'message': message,
              'coverage': '本次未取得网页正文，已有来源仍有效。' if is_fetch else '本次未取得搜索结果，已有来源仍有效。'}
    if attempts_exhausted:
        result['attemptsExhausted'] = True
    if category:
        result['errorCategory'] = category
    if is_fetch:
        url = public_address(value)
        if url:
            result['url'] = url
            result['requestedUrl'] = url
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        if is_fetch and result.get('url'):
            from app.tasks.nodes.node_execution import active_node
            active = active_node.get()
            failures = dict(job.result.get('webReadFailures', {}))
            # One record per execution node, updated at each real attempt.
            # Recovery must not borrow a different call's redirect/failure.
            if active and failed_url is not None:
                failures[active[0]] = {'failedUrl': public_address(failed_url), 'links': redirect_links(links)}
                job.result = {**job.result, 'webReadFailures': failures}
            failure = failures.get(active[0], {}) if active and failed_url is None else {}
            failed = public_address(failed_url) if failed_url is not None else failure.get('failedUrl')
            if failed:
                result['failedUrl'] = failed
            sources = dict(job.result.get('webSources', {}))
            redirects = dict(job.result.get('webRedirects', {}))
            observed = redirect_links(links if links is not None else failure.get('links', []))
            if observed:
                redirects[result['url']] = redirect_links([*redirects.get(result['url'], []), *observed])
                for item in observed:
                    # Retain stronger previous body/snippet evidence and the
                    # exact redirect relation separately for recovery/replay.
                    if item['url'] not in sources:
                        sources[item['url']] = item
                    origin = item['discoveredOn']
                    previous = sources.get(origin, {})
                    if previous.get('evidenceType') not in ('search_snippet', 'page_text'):
                        sources[origin] = {**previous, 'url': origin, 'title': previous.get('title') or urlsplit(origin).hostname,
                                           'evidenceType': 'page_link', 'discoveryType': 'http_redirect',
                                           'redirectTo': item['url'], 'fetchState': 'redirected'}
                        sources[origin].pop('fetchError', None)
                job.result = {**job.result, 'webSources': sources, 'webRedirects': redirects}
            observed = redirects.get(result['url'], [])
            if observed:
                result['links'] = observed
        # A failure is not a source. Preserve any previous successful excerpt
        # without converting a search hit into proof that its body was read.
        if is_fetch:
            previous = job.result.get('webSources', {}).get(result.get('url'), {})
            result['sourceDiscovered'] = bool(previous)
            result['evidenceLevel'] = previous.get('evidenceType', 'unverified_url')
            if previous:
                result['availableEvidence'] = {key: previous[key] for key in ('url', 'title', 'snippet', 'evidenceType', 'discoveredOn', 'discoveryType', 'redirectTo', 'offset', 'endOffset', 'totalChars', 'truncated') if key in previous}
            else:
                result['coverage'] = '仅尝试该地址，未取得网页正文或发现该来源；其他已有来源仍有效。'
            if result.get('links'):
                result['coverage'] = '本次未取得网页正文；links 是服务器实际返回的跳转目标，不代表目标正文已读取。'
        failed = result.get('failedUrl', result.get('url'))
        if is_fetch and failed in job.result.get('webSources', {}) and (result.get('failedUrl') or not result.get('links')):
            sources = dict(job.result['webSources'])
            sources[failed] = {**sources[failed], 'fetchState': 'unavailable', 'fetchError': code}
            job.result = {**job.result, 'webSources': sources}
    return json.dumps(result, ensure_ascii=False)


async def research(context, operation, value, *, is_fetch=False):
    async with context.sessions() as db:
        await lease(db, context)
    try:
        result = await operation(value)
    except web_research.WebTemporaryError as error:
        if context.node_retry:
            if is_fetch:
                # Node retry journals keep failure classification, not Python
                # exception attributes. Persist real Location evidence before
                # raising so exhausted/replayed nodes can still return it.
                await unavailable(context, value, str(error), is_fetch=True, code='web_network', category=error.category, links=error.links, failed_url=error.failed_url)
            raise
        return await unavailable(context, value, str(error), is_fetch=is_fetch, code='web_network', category=error.category, links=error.links, failed_url=error.failed_url)
    except web_research.WebResearchError as error:
        return await unavailable(context, value, str(error), is_fetch=is_fetch, code=error.code, category=error.category, links=error.links, failed_url=error.failed_url)
    async with context.sessions.begin() as db:
        job, _ = await lease(db, context)
        records = [] if result.get('state') == 'not_found' else [result, *result.get('links', [])] if 'url' in result else result.get('items', [])
        sources = dict(job.result.get('webSources', {}))
        for item in records:
            if item.get('evidenceType') == 'page_text' and not (is_fetch and item is result and result.get('text', '').strip()):
                continue
            previous = sources.get(item['url'], {})
            evidence = {key: item[key] for key in ('url', 'title', 'requestedUrl', 'discoveredOn', 'evidenceType', 'offset', 'endOffset', 'totalChars', 'nextOffset', 'truncated') if key in item}
            if item.get('evidenceType') == 'search_snippet' and isinstance(item.get('snippet'), str):
                evidence['snippet'] = item['snippet'][:400]
            rank = {'page_link': 1, 'search_snippet': 2, 'page_text': 3}
            if rank.get(item.get('evidenceType'), 0) < rank.get(previous.get('evidenceType'), 0):
                continue
            sources[item['url']] = {**previous, **evidence,
                                    'fetchState': 'read' if item.get('evidenceType') == 'page_text' else previous.get('fetchState', 'not_read')}
            if item.get('evidenceType') == 'page_text':
                sources[item['url']].pop('snippet', None)
                sources[item['url']].pop('fetchError', None)
        # This is the job's discovery ledger, not an evictable display cache.
        # Tool/result limits bound its size; JSONB key order is not recency.
        # Forgetting a source would make a later failed fetch deny its discovery.
        job.result = {**job.result, 'webSources': sources}
    return json.dumps(result, ensure_ascii=False)


@tool
async def web_search(query: str, runtime: ToolRuntime[RunContext], domains: list[str] | None = None) -> str:
    """Find public links, titles and snippets using concise keywords.
    These can answer link-only requests without fetching the pages.
    domains filters up to five domains/subdomains; no hits do not prove absence.
    newEvidenceCount counts new URL/title/snippet combinations, not relevance.
    """
    return await research(runtime.context, lambda value: web_research.web_search(value, domains=domains), query)


@tool
async def web_fetch(url: str, runtime: ToolRuntime[RunContext], offset: int = 0, find: str = '', match_index: int = 0, refresh: bool = False) -> str:
    """Read a public page's body excerpt (page_text) for missing facts.
    find: literal case-insensitive phrase (1-200 chars); match_index/nextMatchIndex
    select a match from 0. Otherwise offset/nextOffset page sequentially.
    Do not combine find and nonzero offset. Ranges are zero-based, end-exclusive;
    totalChars is extracted length.
    not_found gives no passage, not a negative factual finding.
    links are observed titles/URLs with a referring page (page_link), not target
    body text. URL fragments are not resolved. refresh requests a fresh snapshot;
    cacheHit/fetchedAt identify the returned snapshot.
    """
    from app.agent.runtime.tool_progress.service import web_cache
    cache = await web_cache(runtime.context, url)
    return await research(runtime.context, lambda value: web_research.web_fetch(value, offset=offset, find=find, match_index=match_index, cache=cache, refresh=refresh), url, is_fetch=True)


WEB_TOOLS = [web_search, web_fetch]
