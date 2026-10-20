"""Real libcurl requests against owned origins; no public network or model calls."""
import asyncio
import contextlib
import gzip
import ssl
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from curl_cffi import CurlError, CurlHttpVersion, CurlOpt

from app.integrations import web_curl, web_research as web

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def origin(monkeypatch, tmp_path):
    servers, tasks, calls, options, names, connections = [], set(), [], [], [], []
    routes = {}
    stall_paths, closed_paths, informational = set(), set(), {}
    opened, closed = asyncio.Event(), asyncio.Event()
    original_url = web.public_url
    original_session = web_curl.AsyncSession
    allowed_ports = set()
    certificate = None

    def controlled_url(value):
        url = httpx.URL(value)
        # Only this test's fake host and owned ephemeral ports may use loopback.
        # All other destinations keep the real production URL validator.
        if url.host in ('public-web.test', '::1') and url.port in allowed_ports:
            original_url(str(url.copy_with(host='public-web.test', port=443 if url.scheme == 'https' else 80)))
            return url
        return original_url(value)

    async def resolve(host, port):
        assert host in ('public-web.test', '::1') and port in allowed_ports
        return ['127.0.0.1']

    def session(**kwargs):
        options.append(kwargs.copy())
        if certificate:
            kwargs['verify'] = str(certificate)
        return original_session(**kwargs)

    async def handle(reader, writer):
        task = asyncio.current_task()
        path = None
        tasks.add(task)
        connections.append(writer)
        try:
            raw = await reader.readuntil(b'\r\n\r\n')
            lines = raw.decode('iso-8859-1').split('\r\n')
            path = lines[0].split()[1]
            headers = dict(line.split(': ', 1) for line in lines[1:] if ': ' in line)
            calls.append((path, {key.lower(): value for key, value in headers.items()}))
            opened.set()
            route = routes.get(path, (200, {'Content-Type': 'text/html; charset=utf-8'}, b'<title>Owned</title><main>Readable body</main>'))
            if route == 'hang':
                await reader.read()
                return
            status, response_headers, body = route
            response_headers = {'Content-Length': str(len(body)), 'Connection': 'close', **response_headers}
            writer.write(informational.get(path, b''))
            writer.write(f'HTTP/1.1 {status} Owned\r\n'.encode() + ''.join(f'{key}: {value}\r\n' for key, value in response_headers.items()).encode() + b'\r\n')
            if path in stall_paths:
                await writer.drain()
                await reader.read()
                return
            for index in range(0, len(body), 16000):
                writer.write(body[index:index + 16000])
                await writer.drain()
                await asyncio.sleep(0)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()
            tasks.discard(task)
            closed_paths.add(path)
            closed.set()

    async def start(tls=False, trusted=True, literal=False):
        nonlocal certificate
        context = None
        if tls:
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'public-web.test')])
            now = datetime.now(timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                    .public_key(key.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
                    .add_extension(x509.SubjectAlternativeName([x509.DNSName('public-web.test')]), critical=False)
                    .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                    .sign(key, hashes.SHA256()))
            certificate = tmp_path / 'ca.pem'
            certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            private = tmp_path / 'key.pem'
            private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certificate, private)
            context.set_servername_callback(lambda socket, name, ctx: names.append(name))
            if not trusted:
                certificate = None
        server = await asyncio.start_server(handle, '127.0.0.1', 0, ssl=context)
        servers.append(server)
        port = server.sockets[0].getsockname()[1]
        allowed_ports.add(port)
        return f'{"https" if tls else "http"}://{"[::1]" if literal else "public-web.test"}:{port}'

    monkeypatch.setattr(web, 'public_url', controlled_url)
    monkeypatch.setattr(web_curl, 'public_url', controlled_url)
    monkeypatch.setattr(web_curl, 'public_addresses', resolve)
    monkeypatch.setattr(web_curl, 'AsyncSession', session)
    yield type('Origin', (), {'start': staticmethod(start), 'routes': routes, 'calls': calls, 'options': options,
                             'names': names, 'opened': opened, 'closed': closed, 'stall_paths': stall_paths,
                             'closed_paths': closed_paths, 'informational': informational})()
    for writer in connections:
        writer.close()
    for server in servers:
        server.close()
        await server.wait_closed()
    for task in tuple(tasks):
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def test_native_profile_pinned_connection_and_no_ambient_credentials(origin, monkeypatch):
    for key in ('ALL_PROXY', 'all_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
        monkeypatch.setenv(key, 'http://127.0.0.1:1')
    url = await origin.start()
    page = await web.web_fetch(url + '/article')
    assert page['text'] == 'Readable body' and page['url'] == url + '/article'
    path, headers = origin.calls[0]
    assert path == '/article' and headers['host'] == url.removeprefix('http://')
    assert 'Chrome/150.' in headers['user-agent'] and 'python-httpx' not in headers['user-agent']
    assert headers['accept-language'].startswith('zh-CN')
    assert 'text/html' in headers['accept'] and 'image/avif' in headers['accept']
    assert not {'cookie', 'authorization', 'proxy-authorization'}.intersection(headers)
    configuration = origin.options[0]
    options = configuration['curl_options']
    port = httpx.URL(url).port
    assert options[CurlOpt.RESOLVE] == [f'public-web.test:{port}:127.0.0.1'.encode()]
    assert options[CurlOpt.PROXY] == '' and options[CurlOpt.NOPROXY] == '*'
    assert options[CurlOpt.PROTOCOLS] == options[CurlOpt.REDIR_PROTOCOLS] == 3
    assert options[CurlOpt.FOLLOWLOCATION] == options[CurlOpt.HSTS_CTRL] == 0
    assert CurlOpt.ALTSVC not in options and CurlOpt.ALTSVC_CTRL not in options
    assert options[CurlOpt.HTTP_VERSION] == CurlHttpVersion.V2TLS
    assert options[CurlOpt.SSL_VERIFYPEER] == 1 and options[CurlOpt.SSL_VERIFYHOST] == 2
    assert options[CurlOpt.TIMEOUT_MS] == 8000 and options[CurlOpt.CONNECTTIMEOUT_MS] == 5000
    assert configuration['trust_env'] is False and configuration['verify'] is True


async def test_ipv6_literal_resolve_rule_reaches_only_pinned_socket(origin):
    # Both the test URL and socket are owned loopback addresses; production
    # validates global literals before reaching the same libcurl option path.
    url = await origin.start(literal=True)
    assert (await web.web_fetch(url))['text'] == 'Readable body'
    assert origin.calls[0][1]['host'] == url.removeprefix('http://')


async def test_real_tls_keeps_original_sni_and_certificate_hostname(origin):
    url = await origin.start(tls=True)
    assert (await web.web_fetch(url))['text'] == 'Readable body'
    assert origin.names == ['public-web.test']
    assert origin.calls[0][1]['host'] == url.removeprefix('https://')


async def test_untrusted_tls_certificate_is_rejected(origin):
    url = await origin.start(tls=True, trusted=False)
    with pytest.raises(web.WebTemporaryError) as caught:
        await web.web_fetch(url)
    # libcurl CURLE_PEER_FAILED_VERIFICATION, not a manufactured HTTP failure.
    assert caught.value.category == 'certificate' and caught.value.__cause__.code == 60
    assert not origin.calls


async def test_redirects_revalidate_targets_and_do_not_forward_cookie(origin):
    url = await origin.start()
    origin.routes['/redirect'] = (302, {'Location': '/target', 'Set-Cookie': 'secret=forbidden'}, b'')
    await web.web_fetch(url + '/redirect')
    assert [entry[0] for entry in origin.calls] == ['/redirect', '/target']
    assert 'cookie' not in origin.calls[-1][1] and len(origin.options) == 2
    origin.routes['/private'] = (302, {'Location': 'http://127.0.0.1/private'}, b'')
    with pytest.raises(web.WebResearchError) as caught:
        await web.web_fetch(url + '/private')
    assert caught.value.code == 'blocked_url' and origin.calls[-1][0] == '/private'
    assert len(origin.options) == 3


async def test_mixed_dns_answers_never_start_curl(monkeypatch):
    async def resolver(*args, **kwargs):
        return [(2, 1, 6, '', ('8.8.8.8', 443)), (2, 1, 6, '', ('127.0.0.1', 443))]
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', resolver)
    monkeypatch.setattr(web_curl, 'AsyncSession', lambda **kwargs: pytest.fail('must reject before connecting'))
    with pytest.raises(web.WebResearchError) as caught:
        await web.web_fetch('https://public-web.test/')
    assert caught.value.code == 'blocked_url'


async def test_rss_and_compressed_body_are_decoded_once(origin):
    url = await origin.start()
    content = '<rss><channel><item><title>正文</title><link>https://example.org/</link></item></channel></rss>'.encode()
    origin.routes['/rss'] = (200, {'Content-Type': 'application/rss+xml; charset=utf-8', 'Content-Encoding': 'gzip'}, gzip.compress(content))
    _, raw, mime = await web.fetch_html(url + '/rss', xml=True)
    assert raw == content.decode() and mime == 'application/rss+xml'
    assert 'application/rss+xml' in origin.calls[0][1]['accept']
    text = '压缩正文。' * 100
    origin.routes['/html'] = (200, {'Content-Type': 'text/html; charset=utf-8', 'Content-Encoding': 'gzip'}, gzip.compress(f'<main>{text}</main>'.encode()))
    assert (await web.web_fetch(url + '/html'))['text'] == text


@pytest.mark.parametrize('compressed', [False, True])
async def test_decoded_limit_aborts_receive_callback(origin, monkeypatch, compressed):
    url = await origin.start()
    monkeypatch.setattr(web, 'MAX_BYTES', 1024)
    body = b'x' * 100000
    headers = {'Content-Type': 'text/plain'}
    if compressed:
        body = gzip.compress(body)
        headers['Content-Encoding'] = 'gzip'
        assert len(body) < 1024
    origin.routes['/huge'] = (200, headers, body)
    with pytest.raises(web.WebResearchError) as caught:
        await web.web_fetch(url + '/huge')
    assert caught.value.code == 'web_limit'
    assert len(origin.calls) == 1


@pytest.mark.parametrize('status,headers,body,code,temporary', [
    (403, {'cf-mitigated': 'challenge'}, b'', 'web_challenge', False),
    (200, {}, b'<title>Just a moment...</title><script src="/cdn-cgi/challenge-platform/a"></script>', 'web_challenge', False),
    (403, {}, b'denied', 'http_403', False),
    (429, {}, b'wait', 'unavailable', True),
])
async def test_failure_classification_without_retry(origin, status, headers, body, code, temporary):
    url = await origin.start()
    origin.routes['/failure'] = (status, {'Content-Type': 'text/html', **headers}, body)
    with pytest.raises(web.WebResearchError) as caught:
        await web.web_fetch(url + '/failure')
    assert caught.value.code == code and isinstance(caught.value, web.WebTemporaryError) is temporary
    assert len(origin.calls) == 1


@pytest.mark.parametrize('status,headers,code,temporary', [
    (401, {}, 'http_401', False),
    (403, {}, 'http_403', False),
    (429, {}, 'unavailable', True),
    (200, {'Cf-Mitigated': 'challenge'}, 'web_challenge', False),
    (403, {'Cf-Mitigated': 'challenge'}, 'web_challenge', False),
    (200, {'Content-Type': 'application/pdf'}, 'unavailable', False),
    (200, {'Content-Length': '1000001'}, 'web_limit', False),
    (302, {}, 'unavailable', False),
])
async def test_final_header_rejection_does_not_wait_for_stalled_body(origin, status, headers, code, temporary):
    url = await origin.start()
    origin.routes['/slow'] = (status, {'Content-Type': 'text/html', **headers}, b'body never sent')
    origin.stall_paths.add('/slow')
    # The origin cannot finish the response. Completion must come from headers,
    # well before the unchanged eight-second native request deadline.
    async with asyncio.timeout(1):
        with pytest.raises(web.WebResearchError) as caught:
            await web.web_fetch(url + '/slow')
        await origin.closed.wait()
    assert caught.value.code == code and isinstance(caught.value, web.WebTemporaryError) is temporary
    assert caught.value.__cause__ is None
    assert len(origin.calls) == 1 and '/slow' in origin.closed_paths


async def test_redirect_headers_follow_target_without_waiting_for_body(origin):
    url = await origin.start()
    origin.routes['/slow'] = (302, {'Location': '/article', 'Set-Cookie': 'secret=forbidden'}, b'body never sent')
    origin.stall_paths.add('/slow')
    async with asyncio.timeout(1):
        result = await web.web_fetch(url + '/slow')
        await origin.closed.wait()
    assert result['text'] == 'Readable body' and result['url'] == url + '/article'
    assert [entry[0] for entry in origin.calls] == ['/slow', '/article']
    assert '/slow' in origin.closed_paths and 'cookie' not in origin.calls[1][1]


async def test_informational_headers_do_not_override_final_response(origin, monkeypatch):
    url = await origin.start()
    origin.informational['/article'] = (
        b'HTTP/1.1 100 Continue\r\n\r\n'
        b'HTTP/1.1 103 Early Hints\r\nCF-Mitigated: challenge\r\n'
        b'Content-Type: application/pdf\r\nLink: </style.css>; rel=preload\r\n\r\n'
    )
    body = b'All final response bytes'
    monkeypatch.setattr(web, 'MAX_BYTES', len(body))
    origin.routes['/article'] = (200, {'cOnTeNt-TyPe': 'text/plain; charset=utf-8', 'X-Tag': 'one', 'x-tag': 'two'}, body)
    result = await web.web_fetch(url + '/article')
    assert result['text'] == body.decode()
    assert len(origin.calls) == 1


async def test_readable_header_still_waits_for_body_and_times_out(origin, monkeypatch):
    url = await origin.start()
    origin.routes['/slow'] = (200, {'Content-Type': 'text/plain'}, b'body never sent')
    origin.stall_paths.add('/slow')
    monkeypatch.setattr(web_curl, 'REQUEST_SECONDS', 0.05)
    with pytest.raises(web.WebTemporaryError) as caught:
        await web.web_fetch(url + '/slow')
    await asyncio.wait_for(origin.closed.wait(), 2)
    assert caught.value.category == 'timeout' and caught.value.__cause__.code == 28
    assert '/slow' in origin.closed_paths


async def test_cancellation_closes_real_pending_socket(origin):
    url = await origin.start()
    origin.routes['/hang'] = 'hang'
    task = asyncio.create_task(web.web_fetch(url + '/hang'))
    await asyncio.wait_for(origin.opened.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(origin.closed.wait(), 2)


async def test_request_timeout_closes_socket_and_is_temporary(origin, monkeypatch):
    url = await origin.start()
    origin.routes['/hang'] = 'hang'
    monkeypatch.setattr(web_curl, 'REQUEST_SECONDS', 0.05)
    monkeypatch.setattr(web_curl, 'CONNECT_SECONDS', 0.03)
    with pytest.raises(web.WebTemporaryError) as caught:
        await web.web_fetch(url + '/hang')
    assert caught.value.category == 'timeout'
    await asyncio.wait_for(origin.closed.wait(), 2)
    assert len(origin.calls) == 1


@pytest.mark.parametrize('code,category', [
    (6, 'dns'), (7, 'connection'), (28, 'timeout'), (35, 'tls'),
    (60, 'certificate'), (77, 'certificate'), (18, 'transfer'),
    (52, 'transfer'), (55, 'transfer'), (56, 'transfer'), (92, 'transfer'),
    (999, 'network'),
])
async def test_native_failure_categories_do_not_depend_on_raw_error_text(monkeypatch, code, category):
    calls = []
    async def resolve(*args):
        return ['8.8.8.8']
    async def failed_get(self, url, **kwargs):
        calls.append(url)
        raise CurlError('raw diagnostic with credentials must not reach the model', code=code)
    monkeypatch.setattr(web_curl, 'public_addresses', resolve)
    monkeypatch.setattr(web_curl.AsyncSession, 'get', failed_get)
    with pytest.raises(web.WebTemporaryError) as caught:
        await web.web_fetch('https://example.org/')
    assert caught.value.category == category and caught.value.__cause__.code == code
    assert 'raw diagnostic' not in str(caught.value) and len(calls) == 1


async def test_non_get_cannot_reach_dns_or_network(monkeypatch):
    monkeypatch.setattr(web_curl, 'public_addresses', lambda *args: pytest.fail('no DNS for writes'))
    async with web.PublicTransport() as transport:
        with pytest.raises(web.WebResearchError) as caught:
            await transport.handle_async_request(httpx.Request('POST', 'https://example.org/'))
    assert caught.value.code == 'blocked_url'
