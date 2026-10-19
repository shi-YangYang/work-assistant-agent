"""Bounded public web research; no user credentials, shell or private URLs."""
import asyncio
import ipaddress
import json
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree
import httpx
from .web_curl import PublicTransport

MAX_BYTES = 1_000_000
PAGE_CHARS = 3000


class WebResearchError(ValueError):
    def __init__(self, message, *, code='unavailable', category=''):
        super().__init__(message)
        self.code = code
        self.category = category
        self.links = []
        self.failed_url = ''


class WebTemporaryError(WebResearchError):
    def __init__(self, message=None, *, category='network'):
        messages = {
            'dns': '网页域名暂时无法解析，请稍后再试',
            'connection': '无法连接网页服务器，请稍后再试',
            'timeout': '网页请求超时，请稍后再试',
            'tls': '网页安全连接建立失败，请稍后再试',
            'certificate': '网页安全证书校验失败，请稍后再试',
            'transfer': '网页数据传输未完成，请稍后再试',
            'network': '网页请求超时或网络不可用，请稍后再试',
        }
        super().__init__(message or messages.get(category, messages['network']), category=category)


def public_url(value):
    try:
        url = httpx.URL(value)
        host = url.host
        if url.scheme not in ('http', 'https') or not host or url.username or url.password or url.port not in (None, 80, 443) or len(value) > 2048:
            raise ValueError()
        if host.rstrip('.').lower() == 'localhost' or host.lower().endswith(('.localhost', '.local', '.internal')):
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError()
        return url.copy_with(fragment=None)
    except (ValueError, httpx.InvalidURL) as error:
        raise WebResearchError('仅支持公开的 HTTP(S) 网页地址', code='blocked_url') from error


async def public_addresses(host, port):
    try:
        rows = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        if error.errno == socket.EAI_AGAIN:
            raise WebTemporaryError(category='dns') from error
        raise WebResearchError('网页域名无法解析', category='dns') from error
    except (OSError, UnicodeError) as error:
        raise WebResearchError('网页域名无法解析', category='dns') from error
    addresses = list(dict.fromkeys(row[4][0] for row in rows))
    if not addresses or any(not ipaddress.ip_address(value).is_global for value in addresses):
        raise WebResearchError('不能访问本机、内网或非公开地址', code='blocked_url')
    return addresses


def response_body_type(response, *, xml=False):
    """Shared final-header policy; redirects need no response body."""
    if response.headers.get('cf-mitigated', '').lower() == 'challenge':
        raise WebResearchError('网站要求人机验证，未取得正文', code='web_challenge')
    if response.status_code in (301, 302, 303, 307, 308):
        return None
    if response.status_code in (408, 429, 500, 502, 503, 504):
        category = {408: 'http_timeout', 429: 'rate_limit'}.get(response.status_code, 'server')
        raise WebTemporaryError(f'公开网页服务暂时不可用（HTTP {response.status_code}）', category=category)
    if response.status_code != 200:
        raise WebResearchError(f'网页暂不可访问（HTTP {response.status_code}）', code=f'http_{response.status_code}')
    mime = response.headers.get('content-type', '').split(';')[0].strip().lower()
    if mime not in (('text/xml', 'application/xml', 'application/rss+xml', 'text/html') if xml else ('text/html', 'application/xhtml+xml', 'text/plain')):
        raise WebResearchError('该地址不是可读取的文字网页')
    if int(response.headers.get('content-length', '0')) > MAX_BYTES:
        raise WebResearchError('网页过大，请提供更具体的页面', code='web_limit')
    return mime


async def fetch_html(url, *, transport=None, xml=False):
    current = str(public_url(url))
    redirects = []
    rejected_location = False
    redirected = False

    def failure(error):
        # A Location is an observed link, not evidence of a readable target.
        # Never retain the last hop when URL/DNS policy rejected its destination.
        links = redirects
        if not rejected_location and (error.code == 'blocked_url' or error.category == 'dns'):
            links = [item for item in links if item['url'] != current]
        error.links = links
        # This address reached a public-network attempt. A rejected URL or
        # unresolved DNS target cannot be promoted into public source metadata.
        if not redirected and not rejected_location and error.code != 'blocked_url' and error.category != 'dns':
            error.failed_url = current
        return error

    try:
        async with asyncio.timeout(20):
            async with httpx.AsyncClient(transport=transport or PublicTransport(xml=xml), trust_env=False, follow_redirects=False, timeout=httpx.Timeout(8, connect=5), headers={'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8', **({'Accept': 'application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.5'} if xml else {})}) as client:
                for _ in range(4):
                    redirected = False
                    async with client.stream('GET', current) as response:
                        mime = response_body_type(response, xml=xml)
                        if mime is None:
                            redirected = True
                            target = response.headers.get('location')
                            if not target:
                                raise WebResearchError('网页跳转缺少地址')
                            try:
                                destination = str(public_url(urljoin(current, target)))
                            except WebResearchError:
                                rejected_location = True
                                raise
                            redirects.append({'url': destination, 'title': urlsplit(destination).hostname,
                                              'evidenceType': 'page_link', 'discoveryType': 'http_redirect',
                                              'discoveredOn': current, 'fetchState': 'not_read'})
                            current = destination
                            continue
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw) > MAX_BYTES:
                                raise WebResearchError('网页过大，请提供更具体的页面', code='web_limit')
                        encoding = response.encoding or 'utf-8'
                        value = raw.decode(encoding, errors='replace')
                        if mime in ('text/html', 'application/xhtml+xml') and challenge_page(value):
                            raise WebResearchError('网站要求人机验证，未取得正文', code='web_challenge')
                        return current, value, mime
                raise WebResearchError('网页跳转次数过多')
    except (httpx.TimeoutException, TimeoutError) as error:
        raise failure(WebTemporaryError(category='timeout')) from error
    except httpx.ConnectError as error:
        raise failure(WebTemporaryError(category='connection')) from error
    except (httpx.ReadError, httpx.WriteError, httpx.ProtocolError) as error:
        raise failure(WebTemporaryError(category='transfer')) from error
    except httpx.HTTPError as error:
        raise failure(WebTemporaryError()) from error
    except (ValueError, LookupError) as error:
        if isinstance(error, WebResearchError):
            raise failure(error)
        raise failure(WebResearchError('网页响应格式不受支持')) from error


def challenge_page(value):
    lowered = value.lower()
    title = re.search(r'<title[^>]*>\s*(.*?)\s*</title>', lowered, re.DOTALL)
    return ('/cdn-cgi/challenge-platform/' in lowered or
            bool(title and title.group(1) in ('just a moment...', 'verify you are human', 'access denied')
                 and ('captcha' in lowered or 'cloudflare' in lowered)))


class TextPage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.in_title = False
        self.title = []
        self.parts = []
        self.regions = {'main': [], 'article': []}
        self.depths = dict.fromkeys(self.regions, 0)
        self.links = []
        self.anchor = None

    def append(self, value):
        self.parts.append(value)
        for name, depth in self.depths.items():
            if depth:
                self.regions[name].append(value)

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.anchor = {'href': dict(attrs).get('href', ''), 'parts': []}
        if tag in self.depths:
            self.depths[tag] += 1
        if tag in ('script', 'style', 'noscript', 'svg', 'template', 'nav', 'aside', 'footer'):
            self.skip += 1
        if tag == 'title':
            self.in_title = True
        if tag in ('p', 'div', 'section', 'article', 'li', 'tr', 'h1', 'h2', 'h3', 'br') and not self.skip:
            self.append('\n')

    def handle_endtag(self, tag):
        if tag == 'a' and self.anchor:
            if len(self.links) < 300:
                self.links.append(self.anchor)
            self.anchor = None
        if tag in self.depths:
            self.depths[tag] = max(0, self.depths[tag] - 1)
        if tag in ('script', 'style', 'noscript', 'svg', 'template', 'nav', 'aside', 'footer') and self.skip:
            self.skip -= 1
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.anchor:
            self.anchor['parts'].append(data)
        if self.skip:
            return
        if self.in_title:
            self.title.append(data)
        else:
            self.append(data)


def extract_page(html, *, include_links=False):
    page = TextPage()
    page.feed(html)
    body = next((''.join(page.regions[name]) for name in ('article', 'main') if ''.join(page.regions[name]).strip()), ''.join(page.parts))
    text = '\n'.join(' '.join(line.split()) for line in body.splitlines() if line.strip())
    result = (' '.join(''.join(page.title).split())[:300], text)
    return (*result, page.links) if include_links else result


def page_links(anchors, base_url, excerpt, find=''):
    """Expose observed link targets, never claim their destination was read."""
    candidates, seen = [], {base_url}
    for anchor in anchors:
        title = ' '.join(''.join(anchor['parts']).split())[:120]
        if not title or not anchor['href'] or anchor['href'].startswith('#'):
            continue
        try:
            url = str(public_url(urljoin(base_url, anchor['href'])))
        except WebResearchError:
            continue
        if url in seen:
            continue
        seen.add(url)
        candidates.append(((bool(find) and find.casefold() not in title.casefold(), title not in excerpt), {
            'url': url, 'title': title, 'evidenceType': 'page_link',
            'discoveredOn': base_url, 'fetchState': 'not_read',
        }))
    links, size = [], 0
    # Relevant article links before site navigation, retaining document order.
    for _, link in sorted(candidates, key=lambda value: value[0]):
        length = len(json.dumps(link, ensure_ascii=False))
        if size + length > 2500:
            continue
        links.append(link)
        size += length
        if len(links) == 8:
            break
    return links


def literal_match(text, query, index):
    """Return case-insensitive literal matches in original-text coordinates."""
    folded, needle = text.casefold(), query.casefold()
    count = folded.count(needle)
    if index >= count:
        return count, None, None
    cursor = 0
    for _ in range(index + 1):
        start = folded.find(needle, cursor)
        cursor = start + len(needle)
    end = cursor
    if len(folded) == len(text):
        return count, start, end
    # Unicode case folding can expand a character (e.g. ß -> ss). Keep the
    # returned range on the original page, without allocating a per-byte map.
    cursor, original_start = 0, None
    for position, character in enumerate(text):
        cursor += len(character.casefold())
        if original_start is None and cursor > start:
            original_start = position
        if cursor >= end:
            return count, original_start, position + 1


async def read_page(url, *, transport=None):
    from datetime import datetime, timezone
    final, raw, mime = await fetch_html(url, transport=transport)
    title, text, anchors = extract_page(raw, include_links=True) if mime != 'text/plain' else ('', raw, [])
    if not text.strip():
        raise WebResearchError('网页没有可读取正文，可能需要登录或 JavaScript')
    return {'final': final, 'title': title, 'text': text, 'anchors': anchors,
            'fetchedAt': datetime.now(timezone.utc).isoformat()}


async def web_fetch(url, *, offset=0, find='', match_index=0, transport=None, cache=None, refresh=False):
    if type(offset) is not int or offset < 0:
        raise WebResearchError('网页阅读位置无效')
    if not isinstance(find, str) or len(find) > 200 or (find and not find.strip()):
        raise WebResearchError('网页查找词需为 1～200 个字符')
    if type(match_index) is not int or match_index < 0 or (match_index and not find):
        raise WebResearchError('网页匹配序号无效；从 0 开始，需同时提供查找词')
    if find and offset:
        raise WebResearchError('查找词与阅读位置不能同时指定；查找下一处请使用 match_index')
    normalized = str(public_url(url))
    if cache is None:
        page, hit = await read_page(normalized, transport=transport), False
    else:
        page, hit = await cache.get(normalized, lambda: read_page(normalized, transport=transport), refresh=refresh)
    final, title, text, anchors = (page[key] for key in ('final', 'title', 'text', 'anchors'))
    source = {'url': final, 'title': title or urlsplit(final).hostname,
              'sourceType': 'public_web', 'untrusted': True, 'requestedUrl': url,
              'fetchedAt': page['fetchedAt'], 'cacheHit': hit}
    if httpx.URL(url).fragment:
        source['requestedUrl'] = str(httpx.URL(url))
    match = {}
    if find:
        count, start, end = literal_match(text, find, match_index)
        match = {'find': find, 'matchIndex': match_index, 'matchCount': count,
                 'nextMatchIndex': match_index + 1 if match_index + 1 < count else None}
        if start is None:
            return {**source, **match, 'state': 'not_found', 'evidenceType': 'page_search',
                    'totalChars': len(text), 'message': '提取的正文中未找到该词。' if count == 0 else '指定匹配序号不存在。',
                    'coverage': '本次未返回正文片段，不能据此确认或否定网页中的观点。请换用原文关键词，或不带 find 从头阅读。'}
        offset = max(0, min(start - PAGE_CHARS // 3, len(text) - PAGE_CHARS))
        match.update(matchStart=start, matchEnd=end)
    if offset >= len(text):
        raise WebResearchError('网页阅读位置已超出正文范围，请从头读取')
    end = min(offset + PAGE_CHARS, len(text))
    excerpt = text[offset:end]
    links = page_links(anchors, final, excerpt, find)
    return {**source, **match, **({'links': links, 'linkCoverage': '来源页中实际出现的标题和目标链接；目标正文未读取。'} if links else {}), 'text': excerpt, 'offset': offset, 'endOffset': end,
            'totalChars': len(text), 'nextOffset': end if end < len(text) else None,
            'truncated': offset > 0 or end < len(text), 'evidenceType': 'page_text'}


def search_domains(query, domains):
    if domains is not None and (not isinstance(domains, list) or len(domains) > 5):
        raise WebResearchError('搜索站点需为最多 5 个域名')
    requested = domains or re.findall(r'(?<!\S)site:([^\s/]+)', query, re.IGNORECASE)
    normalized = []
    for domain in requested:
        if not isinstance(domain, str) or not domain.strip() or any(c in domain for c in '/:@?#*') or any(c.isspace() for c in domain.strip()):
            raise WebResearchError('搜索站点仅填写域名，不含路径或通配符')
        parsed = public_url('https://' + domain.strip().rstrip('.'))
        host = parsed.host.lower()
        if host not in normalized:
            normalized.append(host)
    return normalized


async def web_search(query, *, domains=None, transport=None):
    if not query.strip() or len(query) > 500:
        raise WebResearchError('搜索词需为 1～500 个字符')
    scope = search_domains(query, domains)
    search_query = query.strip()
    if domains:
        search_query += ' (' + ' OR '.join('site:' + host for host in scope) + ')'
    url = str(httpx.URL('https://www.bing.com/search', params={'q': search_query, 'format': 'rss'}))
    _, raw, _ = await fetch_html(url, transport=transport, xml=True)
    if '<!doctype' in raw.lower() or '<!entity' in raw.lower():
        raise WebResearchError('搜索来源返回了不支持的内容，暂时无法检索')
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as error:
        raise WebResearchError('搜索来源未返回有效结果，可能要求验证或暂时限流') from error
    if root.tag != 'rss' or root.find('channel') is None:
        raise WebResearchError('搜索来源未返回有效结果，暂时无法检索')
    results, filtered, seen = [], 0, set()
    for item in root.findall('./channel/item')[:10]:
        try:
            target = str(public_url(item.findtext('link', '')))
        except WebResearchError:
            continue
        host = httpx.URL(target).host.lower()
        if scope and not any(host == domain or host.endswith('.' + domain) for domain in scope):
            filtered += 1
            continue
        if target in seen:
            continue
        seen.add(target)
        entry = {'title': ' '.join(item.findtext('title', '').split())[:200], 'url': target, 'snippet': extract_page(item.findtext('description', ''))[1][:400], 'evidenceType': 'search_snippet'}
        if len(json.dumps([*results, entry], ensure_ascii=False)) > 4000:
            break
        results.append(entry)
        if len(results) >= 5:
            break
    result = {'query': query, 'provider': 'Bing RSS', 'items': results, 'coverage': '搜索返回的标题、网址和摘要，可用于定位来源；不含网页正文。', 'untrusted': True}
    if scope:
        result.update(domains=scope, filteredCount=filtered)
        if not results:
            result['coverage'] = '本次域名筛选无结果，不代表网页不存在；已有来源仍有效。'
    return result
