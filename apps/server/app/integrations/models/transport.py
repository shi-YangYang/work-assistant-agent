import asyncio
import httpx
import ipaddress
import re
import socket
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from httpcore._backends.auto import AutoBackend
from httpcore import ConnectError, ConnectTimeout
from urllib.parse import urlsplit, urlunsplit


_task_transports = ContextVar('task_model_transports', default=None)
_request_timing = ContextVar('model_request_timing', default=None)
_request_scheme = ContextVar('model_request_scheme', default=None)


def network_timing(event, **fields):
    callback = _request_timing.get()
    if callback:
        callback(event, **fields)


@asynccontextmanager
async def request_timing(callback):
    token = _request_timing.set(callback)
    try:
        yield
    finally:
        _request_timing.reset(token)


@asynccontextmanager
async def task_connections():
    """Reuse sockets only inside one task; request clients keep no shared cookies."""
    transports = {}
    token = _task_transports.set(transports)
    try:
        yield
    finally:
        _task_transports.reset(token)
        await asyncio.gather(*(transport.aclose() for transport in transports.values()), return_exceptions=True)


class ProviderError(ValueError):
    def __init__(self, code, message, status=None, retry_after=None, *, sent=None, output_limit=False):
        super().__init__(message)
        self.code, self.status, self.retry_after, self.sent = code, status, retry_after, sent
        self.output_limit = output_limit


RATE_LIMIT_CODES = frozenset(('rate_limit_exceeded', 'rate_limit_error', 'too_many_requests', 'throttled', 'throttling', 'throttling.ratequota'))
CONTENT_FILTER_CODES = frozenset(('data_inspection_failed', 'datainspectionfailed', 'content_filter', 'content_policy_violation'))


def structured_error(value, *, status=None, delay=None):
    """Map provider codes, never echo untrusted error prose or request data."""
    if not isinstance(value, dict):
        return None
    detail = value.get('error', value)
    if not isinstance(detail, dict):
        return None
    codes = {detail[field].lower() for field in ('code', 'type') if isinstance(detail.get(field), str)}
    if codes & CONTENT_FILTER_CODES:
        return ProviderError('content_filter', '模型服务的内容审核拦截了本次生成。请调整问题后重新发送；原样重试可能仍会失败。', status)
    if codes & RATE_LIMIT_CODES:
        return ProviderError('rate_limit', '服务请求暂时受限，请稍后重试', status or 429, delay)
    if codes & {'insufficient_quota', 'quota_exceeded'}:
        return ProviderError('quota', '服务额度不足，请查看服务商账户', status or 429, delay)
    if codes & {'invalid_api_key', 'authentication_error'}:
        return ProviderError('authentication', '鉴权失败，请核对密钥、模型权限及服务地域', status or 401)
    if codes & {'invalid_request_error', 'invalid_parameter', 'invalidparameter'}:
        return ProviderError('protocol', '服务不支持当前路径、模型或参数，请核对接口配置', status or 400)
    if codes & {'server_error', 'internal_error', 'internalerror', 'service_unavailable', 'serviceunavailable'}:
        return ProviderError('network', '模型服务暂不可用，请稍后重试', status or 503, delay)
    return None


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
            started = time.monotonic()
            network_timing('network.dns.start')
            addresses = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM), timeout=min(timeout or 10, 10))
            network_timing('network.dns.end', elapsed_ms=round((time.monotonic() - started) * 1000, 3))
            ips = list(dict.fromkeys(item[4][0] for item in addresses))
            authority = '[' + host + ']' if ':' in host else host
            scheme = _request_scheme.get() or self.scheme
            origin = f'{scheme}://{authority}' + (f':{port}' if port != (443 if scheme == 'https' else 80) else '')
            if not ips or (origin not in self.settings.model_allowed_origins and not all(allowed_address(ip) for ip in ips)):
                raise ProviderError('address', '服务地址解析到受限制网络，请联系部署管理员')
            phase = 'connect'
            started = time.monotonic()
            network_timing('network.connect.start')
            result = await super().connect_tcp(ips[0], port, timeout, local_address, socket_options)
            network_timing('network.connect.end', elapsed_ms=round((time.monotonic() - started) * 1000, 3))
            return result
        except ProviderError:
            raise
        except (OSError, asyncio.TimeoutError, ConnectError, ConnectTimeout) as error:
            network_timing('network.error', reason=locals().get('phase', 'dns'), error=type(error).__name__, state='not_sent')
            raise ProviderError('network', '无法连接模型服务，请检查地址和网络', sent=False) from None


class LimitedStream(httpx.AsyncByteStream):
    def __init__(self, stream, max_seconds=65, *, streaming=False):
        self.stream, self.max_seconds = stream, max_seconds
        self.streaming = streaming

    async def __aiter__(self):
        size, start = 0, time.monotonic()
        async for chunk in self.stream:
            if time.monotonic() - start > self.max_seconds:
                raise ProviderError('timeout', '模型响应超过本次处理时限，请稍后重试')
            # SSE records are consumed incrementally. Repeated envelopes and
            # discarded reasoning must not exhaust the buffered JSON limit.
            # Bound each line before httpx's line decoder can accumulate it,
            # without imposing a cumulative answer-length limit.
            offset = 0
            if self.streaming:
                for newline in re.finditer(b'[\r\n]', chunk):
                    size += newline.start() - offset
                    if size > 2 * 1024 * 1024:
                        raise ProviderError('limit', '模型单段流式响应过大，已停止接收')
                    size, offset = 0, newline.end()
            size += len(chunk) - offset
            if size > 2 * 1024 * 1024:
                message = '模型单段流式响应过大，已停止接收' if self.streaming else '模型响应内容过大，已停止接收'
                raise ProviderError('limit', message)
            yield chunk

    async def aclose(self):
        await self.stream.aclose()


class SafeTransport(httpx.AsyncHTTPTransport):
    def __init__(self, settings):
        super().__init__(trust_env=False, retries=0, limits=httpx.Limits(max_connections=4, max_keepalive_connections=2))
        self.settings = settings
        self._pool._network_backend = CheckedBackend(settings)

    async def handle_async_request(self, request):
        token = _request_scheme.set(request.url.scheme)
        try:
            response = await super().handle_async_request(request)
        finally:
            _request_scheme.reset(token)
        if response.headers.get('content-encoding', 'identity').lower() != 'identity':
            await response.aclose()
            raise ProviderError('protocol', '模型服务返回了不受支持的压缩响应')
        # Only the bounded streaming chat path supplies its existing node deadline.
        # Other model endpoints retain the original 65-second response cap.
        response.stream = LimitedStream(response.stream, request.extensions.get('paa_model_stream_timeout', 65),
                                        streaming=request.extensions.get('paa_model_streaming', False) and response.is_success)
        return response


class BorrowedTransport(httpx.AsyncBaseTransport):
    def __init__(self, transports, settings):
        self.transports, self.settings = transports, settings

    async def handle_async_request(self, request):
        key = (request.url.scheme, request.url.host, request.url.port, tuple(self.settings.model_allowed_origins))
        if key not in self.transports:
            self.transports[key] = SafeTransport(self.settings)
        return await self.transports[key].handle_async_request(request)

    async def aclose(self):
        pass  # The task owns the pool; a request owns its cookies and headers.


def client(settings):
    shared = _task_transports.get()
    if shared is None:
        transport = SafeTransport(settings)
    else:
        transport = BorrowedTransport(shared, settings)
    return httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(60, connect=10), trust_env=False, follow_redirects=False, headers={'Accept-Encoding': 'identity'})


async def finish_stream(lines):
    """Consume a promptly available HTTP ending, never wait for TCP close.

    The valid model answer has already ended. Only a small bounded tail is
    disposable; a stalled or malformed ending must close instead of reusing
    its socket. Cancellation remains cancellation, not a successful drain.
    """
    size = 0
    try:
        async with asyncio.timeout(.05):
            for _ in range(128):
                try:
                    line = await anext(lines)
                except StopAsyncIteration:
                    return
                size += len(line.encode('utf-8')) + 1
                if size > 8192:
                    return
    except (TimeoutError, httpx.HTTPError, ProviderError):
        # The response context closes any unconsumed stream. No background
        # drain outlives this request, and post-DONE bytes never reach callers.
        return


def status_error(response):
    code = response.status_code
    if 200 <= code < 300:
        return
    if code in (401, 403):
        raise ProviderError('authentication', '鉴权失败，请核对密钥、模型权限及服务地域', code)
    try:
        structured = structured_error(response.json(), status=code, delay=retry_after(response))
    except (ValueError, httpx.ResponseNotRead):
        structured = None
    if structured:
        raise structured
    if code == 429:
        # Only structured provider codes distinguish temporary throttling from
        # exhausted credits. An ambiguous 429 is not safe to repeat blindly.
        raise ProviderError('quota', '服务额度不足或请求受限，请查看服务商账户', code, retry_after(response))
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
        return ProviderError('timeout', '模型响应超时，请稍后重试')
    if isinstance(error, httpx.HTTPError):
        return ProviderError('network', '模型连接中断，请检查网络后重试')
    return ProviderError('invalid_response', '模型返回内容不符合所选接口，请核对模型能力与参数')
