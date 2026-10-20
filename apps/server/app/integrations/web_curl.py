"""Browser-profile HTTP reads; only validated, pinned public destinations."""
import httpx
from curl_cffi import CurlECode, CurlError, CurlHttpVersion, CurlOpt
from curl_cffi.curl import CURL_WRITEFUNC_ERROR
from curl_cffi.requests import AsyncSession
from .web_policy import MAX_BYTES, WebResearchError, WebTemporaryError, public_addresses, public_url, response_body_type

PROFILE = 'chrome150'
REQUEST_SECONDS = 8
CONNECT_SECONDS = 5

# Classify native error codes, never free-form exception text. A timeout or
# failed TLS handshake alone cannot identify geographic blocking or its cause.
ERROR_CATEGORIES = {
    CurlECode.COULDNT_RESOLVE_HOST: 'dns',
    CurlECode.COULDNT_CONNECT: 'connection',
    CurlECode.OPERATION_TIMEDOUT: 'timeout',
    CurlECode.SSL_CONNECT_ERROR: 'tls',
    CurlECode.SSL_CIPHER: 'tls',
    CurlECode.USE_SSL_FAILED: 'tls',
    CurlECode.SSL_CERTPROBLEM: 'certificate',
    CurlECode.PEER_FAILED_VERIFICATION: 'certificate',
    CurlECode.SSL_CACERT_BADFILE: 'certificate',
    CurlECode.SSL_CRL_BADFILE: 'certificate',
    CurlECode.SSL_ISSUER_ERROR: 'certificate',
    CurlECode.SSL_PINNEDPUBKEYNOTMATCH: 'certificate',
    CurlECode.SSL_INVALIDCERTSTATUS: 'certificate',
    CurlECode.SSL_CLIENTCERT: 'certificate',
    CurlECode.PARTIAL_FILE: 'transfer',
    CurlECode.GOT_NOTHING: 'transfer',
    CurlECode.SEND_ERROR: 'transfer',
    CurlECode.RECV_ERROR: 'transfer',
    CurlECode.HTTP2: 'transfer',
    CurlECode.HTTP2_STREAM: 'transfer',
}


class PublicTransport(httpx.AsyncBaseTransport):
    """Use httpx's response interface without its production network transport."""

    def __init__(self, *, xml=False):
        self.xml = xml

    async def handle_async_request(self, request):
        if request.method != 'GET':
            raise WebResearchError('网页读取仅支持 GET 请求', code='blocked_url')
        url = public_url(str(request.url))
        port = url.port or (443 if url.scheme == 'https' else 80)
        addresses = await public_addresses(url.host, port)
        # Keep the original URL for Host, SNI and certificate verification. Every
        # socket candidate comes from the validated DNS result; no second lookup.
        pinned = ','.join(f'[{value}]' if ':' in value else value for value in addresses)
        host = url.raw_host.decode('ascii')
        resolve_host = f'[{host}]' if ':' in host else host
        options = {
            CurlOpt.RESOLVE: [f'{resolve_host}:{port}:{pinned}'.encode()],
            CurlOpt.PROXY: '', CurlOpt.NOPROXY: '*', CurlOpt.NETRC: 0,
            CurlOpt.PROTOCOLS: 3, CurlOpt.REDIR_PROTOCOLS: 3,
            CurlOpt.FOLLOWLOCATION: 0, CurlOpt.HSTS_CTRL: 0,
            CurlOpt.HTTP_VERSION: CurlHttpVersion.V2TLS,
            CurlOpt.SSL_VERIFYPEER: 1, CurlOpt.SSL_VERIFYHOST: 2,
            CurlOpt.CONNECTTIMEOUT_MS: int(CONNECT_SECONDS * 1000),
            CurlOpt.TIMEOUT_MS: int(REQUEST_SECONDS * 1000),
        }
        body = bytearray()
        too_large = False
        status = 0
        response_headers = []
        headers_complete = False
        early_response = None

        def receive_headers(line):
            nonlocal status, headers_complete, early_response
            if line.startswith(b'HTTP/'):
                try:
                    status = int(line.split(b' ', 2)[1])
                except (IndexError, ValueError):
                    return CURL_WRITEFUNC_ERROR
                response_headers.clear()
                headers_complete = False
            elif not headers_complete and status >= 200:
                if line in (b'\r\n', b'\n'):
                    headers_complete = True
                    response = httpx.Response(status, headers=response_headers, request=request)
                    try:
                        needs_body = response_body_type(response, xml=self.xml) is not None
                    except ValueError:
                        needs_body = False
                    if not needs_body:
                        # This is an intentional header-only completion, not a
                        # network failure. Keep the status for the shared policy.
                        early_response = response
                        return CURL_WRITEFUNC_ERROR
                elif line[:1] in (b' ', b'\t') and response_headers:
                    key, value = response_headers[-1]
                    response_headers[-1] = (key, value + b' ' + line.strip())
                else:
                    key, separator, value = line.partition(b':')
                    if separator:
                        response_headers.append((key, value.strip()))
            # Informational 100/103 blocks and body trailers are not final headers.
            return len(line)

        options[CurlOpt.HEADERFUNCTION] = receive_headers

        def receive(chunk):
            nonlocal too_large
            # libcurl invokes this after gzip/br/zstd decompression. Returning
            # an error stops transfer immediately, without an unbounded queue.
            if len(body) + len(chunk) > MAX_BYTES:
                too_large = True
                return CURL_WRITEFUNC_ERROR
            body.extend(chunk)
            return len(chunk)

        headers = {key: request.headers[key] for key in ('accept', 'accept-language')
                   if key in request.headers and not (key == 'accept' and request.headers[key] == '*/*')}
        # Leave HTML Accept/UA/client hints to the complete browser profile;
        # do not forward httpx's default Accept: */*. RSS explicitly opts in.
        # Alt-Svc is never enabled or persisted. A fresh session per hop also
        # prevents connection/HTTP2 coalescing from bypassing the new DNS pin.
        # A short-lived async session owns all handles, DNS and cookie state.
        # Cancellation unwinds the request and closes its sockets in __aexit__.
        async with AsyncSession(impersonate=PROFILE, default_headers=True,
                                trust_env=False, verify=True, max_clients=1,
                                curl_options=options) as session:
            try:
                result = await session.get(
                    str(url), headers=headers,
                    allow_redirects=False, timeout=REQUEST_SECONDS,
                    accept_encoding='gzip, deflate, br, zstd',
                    content_callback=receive, discard_cookies=True,
                )
            except CurlError as error:
                if early_response is not None:
                    return early_response
                if too_large:
                    raise WebResearchError('网页过大，请提供更具体的页面', code='web_limit') from error
                raise WebTemporaryError(category=ERROR_CATEGORIES.get(error.code, 'network')) from error
        # The body is already decoded by libcurl. Never feed the wire encoding
        # back into httpx, which would decompress a second time.
        headers = [(key, value) for key, value in response_headers
                   if key.lower() not in (b'content-encoding', b'content-length', b'transfer-encoding')]
        return httpx.Response(result.status_code, headers=headers, content=bytes(body), request=request)
