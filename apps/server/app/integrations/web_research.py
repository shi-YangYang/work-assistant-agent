"""Bounded public HTTP research; no browser, shell, credentials or private URLs."""
import asyncio
import ipaddress
import json
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree
import httpx

MAX_BYTES = 1_000_000
PAGE_CHARS = 3000
USER_AGENT = 'work-assistant-agent/0.1'


class WebResearchError(ValueError):
    pass


class WebTemporaryError(WebResearchError):
    pass


def public_url(value):
    try:
        url = httpx.URL(value)
        host = url.host
        if url.scheme not in ('http', 'https') or not host or url.username or url.password or url.port not in (None, 80, 443) or len(value) > 2048:
            raise ValueError()
        if host.rstrip('.').lower() == 'localhost' or host.lower().endswith(('.localhost', '.local', '.internal')):
            raise ValueError()
        return url.copy_with(fragment=None)
    except (ValueError, httpx.InvalidURL) as error:
        raise WebResearchError('仅支持公开的 HTTP(S) 网页地址') from error


async def public_addresses(host, port):
    try:
        rows = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        if error.errno == socket.EAI_AGAIN:
            raise WebTemporaryError('网页域名暂时无法解析，请稍后再试') from error
        raise WebResearchError('网页域名无法解析') from error
    except (OSError, UnicodeError) as error:
        raise WebResearchError('网页域名无法解析') from error
    addresses = list(dict.fromkeys(row[4][0] for row in rows))
    if not addresses or any(not ipaddress.ip_address(value).is_global for value in addresses):
        raise WebResearchError('不能访问本机、内网或非公开地址')
    return addresses


class PublicTransport(httpx.AsyncHTTPTransport):
    async def handle_async_request(self, request):
        url = public_url(str(request.url))
        addresses = await public_addresses(url.host, url.port or (443 if url.scheme == 'https' else 80))
        # Pin the validated IP through the actual TCP connection. Preserve the
        # original Host and TLS SNI/certificate name; no second DNS lookup.
        headers = request.headers.copy()
        headers['host'] = url.netloc.decode('ascii')
        pinned = httpx.Request(request.method, url.copy_with(host=addresses[0]), headers=headers, stream=request.stream, extensions={**request.extensions, 'sni_hostname': url.host})
        return await super().handle_async_request(pinned)


async def fetch_html(url, *, transport=None, xml=False):
    current = str(public_url(url))
    try:
        async with asyncio.timeout(20):
            async with httpx.AsyncClient(transport=transport or PublicTransport(retries=0), trust_env=False, follow_redirects=False, timeout=httpx.Timeout(8, connect=5), headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,text/plain;q=0.9'}) as client:
                for _ in range(4):
                    async with client.stream('GET', current) as response:
                        if response.status_code in (301, 302, 303, 307, 308):
                            target = response.headers.get('location')
                            if not target:
                                raise WebResearchError('网页跳转缺少地址')
                            current = str(public_url(urljoin(current, target)))
                            continue
                        if response.status_code in (408, 429, 500, 502, 503, 504):
                            raise WebTemporaryError(f'公开网页服务暂时不可用（HTTP {response.status_code}）')
                        if response.status_code != 200:
                            raise WebResearchError(f'网页暂不可访问（HTTP {response.status_code}）')
                        mime = response.headers.get('content-type', '').split(';')[0].strip().lower()
                        if mime not in (('text/xml', 'application/xml', 'application/rss+xml', 'text/html') if xml else ('text/html', 'application/xhtml+xml', 'text/plain')):
                            raise WebResearchError('该地址不是可读取的文字网页')
                        if int(response.headers.get('content-length', '0')) > MAX_BYTES:
                            raise WebResearchError('网页过大，请提供更具体的页面')
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw) > MAX_BYTES:
                                raise WebResearchError('网页过大，请提供更具体的页面')
                        encoding = response.encoding or 'utf-8'
                        return current, raw.decode(encoding, errors='replace'), mime
                raise WebResearchError('网页跳转次数过多')
    except (httpx.HTTPError, TimeoutError) as error:
        raise WebTemporaryError('网页请求超时或网络不可用，请稍后再试') from error
    except (ValueError, LookupError) as error:
        if isinstance(error, WebResearchError):
            raise
        raise WebResearchError('网页响应格式不受支持') from error


class TextPage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.in_title = False
        self.title = []
        self.parts = []
        self.regions = {'main': [], 'article': []}
        self.depths = dict.fromkeys(self.regions, 0)

    def append(self, value):
        self.parts.append(value)
        for name, depth in self.depths.items():
            if depth:
                self.regions[name].append(value)

    def handle_starttag(self, tag, attrs):
        if tag in self.depths:
            self.depths[tag] += 1
        if tag in ('script', 'style', 'noscript', 'svg', 'template', 'nav', 'aside', 'footer'):
            self.skip += 1
        if tag == 'title':
            self.in_title = True
        if tag in ('p', 'div', 'section', 'article', 'li', 'tr', 'h1', 'h2', 'h3', 'br') and not self.skip:
            self.append('\n')

    def handle_endtag(self, tag):
        if tag in self.depths:
            self.depths[tag] = max(0, self.depths[tag] - 1)
        if tag in ('script', 'style', 'noscript', 'svg', 'template', 'nav', 'aside', 'footer') and self.skip:
            self.skip -= 1
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.skip:
            return
        if self.in_title:
            self.title.append(data)
        else:
            self.append(data)


def extract_page(html):
    page = TextPage()
    page.feed(html)
    body = next((''.join(page.regions[name]) for name in ('article', 'main') if ''.join(page.regions[name]).strip()), ''.join(page.parts))
    text = '\n'.join(' '.join(line.split()) for line in body.splitlines() if line.strip())
    return ' '.join(''.join(page.title).split())[:300], text


async def web_fetch(url, *, offset=0, transport=None):
    if not isinstance(offset, int) or offset < 0:
        raise WebResearchError('网页阅读位置无效')
    final, raw, mime = await fetch_html(url, transport=transport)
    title, text = extract_page(raw) if mime != 'text/plain' else ('', raw)
    if not text.strip():
        raise WebResearchError('网页没有可读取正文，可能需要登录或 JavaScript')
    if offset >= len(text):
        raise WebResearchError('网页阅读位置已超出正文范围，请从头读取')
    end = offset + PAGE_CHARS
    return {'url': final, 'title': title or urlsplit(final).hostname, 'text': text[offset:end], 'offset': offset, 'nextOffset': end if end < len(text) else None, 'truncated': offset > 0 or end < len(text), 'sourceType': 'public_web', 'untrusted': True}


async def web_search(query, *, transport=None):
    if not query.strip() or len(query) > 500:
        raise WebResearchError('搜索词需为 1～500 个字符')
    url = str(httpx.URL('https://www.bing.com/search', params={'q': query.strip(), 'format': 'rss'}))
    _, raw, _ = await fetch_html(url, transport=transport, xml=True)
    if '<!doctype' in raw.lower() or '<!entity' in raw.lower():
        raise WebResearchError('搜索来源返回了不支持的内容，暂时无法检索')
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as error:
        raise WebResearchError('搜索来源未返回有效结果，可能要求验证或暂时限流') from error
    if root.tag != 'rss' or root.find('channel') is None:
        raise WebResearchError('搜索来源未返回有效结果，暂时无法检索')
    results = []
    for item in root.findall('./channel/item')[:10]:
        try:
            target = str(public_url(item.findtext('link', '')))
        except WebResearchError:
            continue
        entry = {'title': ' '.join(item.findtext('title', '').split())[:200], 'url': target, 'snippet': extract_page(item.findtext('description', ''))[1][:400]}
        if len(json.dumps([*results, entry], ensure_ascii=False)) > 4000:
            break
        results.append(entry)
        if len(results) >= 5:
            break
    return {'query': query, 'provider': 'Bing RSS', 'items': results, 'coverage': '搜索摘要；需要正文时读取对应网页', 'untrusted': True}
