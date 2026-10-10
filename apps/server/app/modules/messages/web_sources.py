"""Web reading receipts, distinct from claim-level verified citations."""
from app.integrations.web_research import WebResearchError, public_url


def source_url(value):
    if not isinstance(value, str) or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        return None
    try:
        return str(public_url(value))
    except WebResearchError:
        return None


def source_title(value, url):
    return ' '.join(str(value or '').split())[:200] or url


def web_citations(result):
    """Only the successful page excerpt records of this message's job qualify.

    Later failed reads do not erase an earlier successful excerpt. Discovery
    links and search snippets are never promoted into page-reading receipts.
    """
    sources = {}
    for row in result.get('webSources', {}).values():
        if row.get('evidenceType') != 'page_text':
            continue
        start, end = row.get('offset'), row.get('endOffset')
        if type(start) is not int or type(end) is not int or not 0 <= start < end:
            continue
        url = source_url(row.get('url'))
        if url:
            sources[url] = {'kind': 'web', 'url': url, 'title': source_title(row.get('title'), url),
                            'evidenceType': 'page_text', 'refetchFailed': row.get('fetchState') == 'unavailable'}
    return list(sources.values())


def web_source_dtos(citations):
    sources = {}
    for row in citations:
        if row.get('kind') != 'web' or row.get('evidenceType') != 'page_text':
            continue
        url = source_url(row.get('url'))
        if url:
            sources[url] = {'url': url, 'title': source_title(row.get('title'), url),
                            'refetchFailed': row.get('refetchFailed', False)}
    return list(sources.values())
