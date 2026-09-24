import asyncio
import httpx
import ipaddress
import socket
import time
from httpcore._backends.auto import AutoBackend
from urllib.parse import urlsplit, urlunsplit


class ProviderError(ValueError):
    def __init__(self, code, message, status=None, retry_after=None, *, sent=None):
        super().__init__(message)
        self.code, self.status, self.retry_after, self.sent = code, status, retry_after, sent


def normalize_url(value, settings):
    try:
        if any(ord(c) < 33 or ord(c) == 127 for c in value) or '\\' in value:
            raise ValueError()
        parts = urlsplit(value)
        if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError()
        port = parts.port
        host = parts.hostname.encode('idna').decode('ascii').lower()
        authority = ('[' + host + ']' if ':' in host else host) + (f':{port}' if port and port != (443 if parts.scheme == 'https' else 80) else '')
        origin = f'{parts.scheme}://{authority}'
        if parts.scheme != 'https' and origin not in settings.model_allowed_origins:
            raise ValueError()
        if parts.scheme not in ('https', 'http'):
            raise ValueError()
        return urlunsplit((parts.scheme, authority, parts.path.rstrip('/'), '', ''))
    except (ValueError, UnicodeError):
        raise ProviderError('address', '服务地址无效：请填写不含账号、查询参数或片段的 HTTPS Base URL') from None


def allowed_address(value):
    ip = ipaddress.ip_address(value.split('%')[0])
    return ip.is_global and not ip.is_multicast and not ip.is_unspecified and not (getattr(ip, 'ipv4_mapped', None) and not allowed_address(str(ip.ipv4_mapped)))


class CheckedBackend(AutoBackend):
    def __init__(self, settings, scheme='https'):
        self.settings = settings
        self.scheme = scheme

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        host = host.decode() if isinstance(host, bytes) else host
        # Resolve exactly once, check ALL answers, then connect only to that numeric IP.
        try:
            addresses = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM), timeout=min(timeout or 10, 10))
            ips = list(dict.fromkeys(item[4][0] for item in addresses))
            authority = '[' + host + ']' if ':' in host else host
            origin = f'{self.scheme}://{authority}' + (f':{port}' if port != (443 if self.scheme == 'https' else 80) else '')
            if not ips or (origin not in self.settings.model_allowed_origins and not all(allowed_address(ip) for ip in ips)):
                raise ProviderError('address', '服务地址解析到受限制网络，请联系部署管理员')
            return await super().connect_tcp(ips[0], port, timeout, local_address, socket_options)
        except ProviderError:
            raise
        except (OSError, asyncio.TimeoutError):
            raise ProviderError('network', '无法连接模型服务，请检查地址和网络', sent=False) from None


class LimitedStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        size, start = 0, time.monotonic()
        async for chunk in self.stream:
            size += len(chunk)
            if size > 2 * 1024 * 1024 or time.monotonic() - start > 65:
                raise ProviderError('limit', '模型响应超过大小或时间限制')
            yield chunk

    async def aclose(self):
        await self.stream.aclose()


class SafeTransport(httpx.AsyncHTTPTransport):
    def __init__(self, settings):
        super().__init__(trust_env=False, retries=0)
        self.settings = settings
        self._pool._network_backend = CheckedBackend(settings)

    async def handle_async_request(self, request):
        self._pool._network_backend.scheme = request.url.scheme
        response = await super().handle_async_request(request)
        if response.headers.get('content-encoding', 'identity').lower() != 'identity':
            await response.aclose()
            raise ProviderError('protocol', '模型服务返回了不受支持的压缩响应')
        response.stream = LimitedStream(response.stream)
        return response


def client(settings):
    return httpx.AsyncClient(transport=SafeTransport(settings), timeout=httpx.Timeout(60, connect=10), trust_env=False, follow_redirects=False, headers={'Accept-Encoding': 'identity'})


def status_error(response):
    code = response.status_code
    if 200 <= code < 300:
        return
    if code in (401, 403):
        raise ProviderError('authentication', '鉴权失败，请核对密钥、模型权限及服务地域', code)
    if code == 429:
        # Only structured provider codes distinguish temporary throttling from
        # exhausted credits. An ambiguous 429 is not safe to repeat blindly.
        try:
            detail = response.json().get('error', {})
            reason = detail.get('code') or detail.get('type')
        except (ValueError, TypeError, AttributeError, httpx.ResponseNotRead):
            reason = None
        temporary = reason in ('rate_limit_exceeded', 'rate_limit_error', 'too_many_requests', 'throttled', 'Throttling', 'Throttling.RateQuota')
        raise ProviderError('rate_limit' if temporary else 'quota', '服务请求暂时受限' if temporary else '服务额度不足或请求受限，请查看服务商账户', code, retry_after(response))
    if code in (400, 404, 405, 415, 422):
        raise ProviderError('protocol', '服务不支持当前路径、模型或参数，请核对接口配置', code)
    if 300 <= code < 400:
        raise ProviderError('address', '服务返回重定向，请直接填写最终服务地址', code)
    raise ProviderError('network', '模型服务暂不可用，请稍后重试', code, retry_after(response))


def retry_after(response):
    from email.utils import parsedate_to_datetime
    import math
    value = response.headers.get('retry-after', '')
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0, seconds) if math.isfinite(seconds) and seconds >= 0 else None


def safe_error(error):
    if isinstance(error, ProviderError):
        return error
    if isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)):
        return ProviderError('network', '未能连接模型服务，请检查地址和网络', sent=False)
    if isinstance(error, (asyncio.TimeoutError, httpx.TimeoutException)):
        return ProviderError('timeout', '请求超时，可能已产生调用费用；请核对后再重试')
    if isinstance(error, httpx.HTTPError):
        return ProviderError('network', '模型连接中断，请检查网络并核对调用记录')
    return ProviderError('invalid_response', '模型返回内容不符合所选接口，请核对模型能力与参数')
