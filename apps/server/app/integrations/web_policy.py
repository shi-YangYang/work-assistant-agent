"""Shared public URL, DNS and response limits for web transports."""
import asyncio
import ipaddress
import socket
import httpx

MAX_BYTES = 1_000_000


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
