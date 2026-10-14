import io
from dataclasses import replace
from types import SimpleNamespace
import httpx
import pytest
from PIL import Image
from app.integrations.models.images import sizes, results, wan
from app.integrations.models.transport import ProviderError, CheckedBackend


def png(width=768, height=768):
    file = io.BytesIO()
    Image.new('RGB', (width, height), 'white').save(file, format='PNG')
    return file.getvalue()


@pytest.mark.parametrize('args,expected', [({}, None), ({'resolution': '2K'}, '2K'), ({'resolution': '1K'}, '1K'),
    ({'use': 'cover'}, '2688*1536'), ({'use': 'phone_wallpaper'}, '1536*2688'), ({'use': 'poster'}, '1728*2368'),
    ({'width': 2048, 'height': 1024, 'use': 'poster'}, '2048*1024'), ({'aspect': '32:18'}, '2688*1536')])
def test_sizes_defaults_priority_and_presets(args, expected):
    assert sizes.normalize(**args) == expected


@pytest.mark.parametrize('aspect', ['8:1', '1:8', '7:5', '5:7', '3:2'])
@pytest.mark.parametrize('resolution', ['1K', '2K'])
def test_nonpreset_exact_ratio_and_area(aspect, resolution):
    w, h = map(int, sizes.normalize(aspect=aspect, resolution=resolution).split('*'))
    a, b = map(int, aspect.split(':'))
    assert w * b == h * a and 768 ** 2 <= w * h <= 2048 ** 2


def test_coprime_ratio_rounds_pixels_without_replacing_ratio():
    w, h = map(int, sizes.normalize(aspect='99999:99998').split('*'))
    assert abs(w / h - 99999 / 99998) < .001 and 768 ** 2 <= w * h <= 2048 ** 2


def test_malformed_extra_results_do_not_hide_valid_images():
    value = {'output': {'choices': [None, {'message': None}, {'message': {'content': None}}, {'message': {'content': [None, {'image': 'https://example.com/good.png'}]}}]}}
    assert wan.images(value) == ['https://example.com/good.png']


@pytest.mark.parametrize('args', [{'resolution': '4K'}, {'width': 0, 'height': 1000}, {'width': True, 'height': 1000},
    {'width': 768}, {'width': 500, 'height': 500}, {'width': 4096, 'height': 2048}, {'aspect': '9:1'},
    {'width': 2048, 'height': 2048, 'aspect': '16:9'}, {'aspect': '1:0'}])
def test_invalid_sizes_fail_before_provider(args):
    with pytest.raises(ProviderError):
        sizes.normalize(**args)


def test_decode_png_actual_dimensions_and_reject_fake_or_large():
    assert results.metadata(png(1000, 800))['width'] == 1000
    for data in (b'<html>oops</html>', b'\x89PNG\r\n\x1a\nwrong', png(8192, 4096), png()[:100]):
        with pytest.raises(ProviderError):
            results.metadata(data)


@pytest.mark.parametrize('url', ['http://example.com/a.png', 'file:///etc/passwd', 'https://x:y@example.com/a.png', 'https://example.com:8443/a.png'])
def test_download_url_rejects_unsafe_shapes(url):
    with pytest.raises(ProviderError):
        results.checked_url(url)


@pytest.mark.asyncio
async def test_native_async_contract_no_thinking_override(monkeypatch):
    calls = []
    def handle(request):
        import json
        calls.append(request)
        if request.method == 'POST':
            body = json.loads(request.content)
            assert body == {'model': 'wan2.7-image', 'input': {'messages': [{'role': 'user', 'content': [{'text': '画一只鸟'}]}]}, 'parameters': {'n': 1, 'enable_sequential': False, 'size': '2048*2048'}}
            assert request.headers['X-DashScope-Async'] == 'enable'
            assert request.url.path == '/api/v1/services/aigc/image-generation/generation'
            return httpx.Response(200, json={'output': {'task_id': 'task-1', 'task_status': 'PENDING'}, 'request_id': 'req-1'})
        assert request.url.path == '/api/v1/tasks/task-1'
        return httpx.Response(200, json={'output': {'task_status': 'SUCCEEDED', 'choices': [{'message': {'content': [{'image': 'https://example.com/image.png?sign=123'}]}}]}})
    monkeypatch.setattr(wan, 'client', lambda settings: httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    settings = SimpleNamespace(model_allowed_origins=())
    config = {'baseUrl': 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'model': 'wan2.7-image', 'protocol': 'dashscope-image'}
    task, req = await wan.submit(settings, config, 'test-secret', '画一只鸟', '2K')
    assert (task, req) == ('task-1', 'req-1')
    assert wan.images(await wan.query(settings, config, 'test-secret', task)) == ['https://example.com/image.png?sign=123']
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('size,expected', [(None, '2048*2048'), ('1K', '1024*1024'), ('2688*1536', '2688*1536')])
async def test_token_plan_sync_contract_same_host_key_and_independent_timeout(monkeypatch, size, expected):
    import json
    calls = []
    def handle(request):
        calls.append(request)
        assert request.url == 'https://token-plan.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation'
        assert request.headers['authorization'] == 'Bearer controlled-token-plan-key'
        assert 'x-dashscope-async' not in request.headers
        assert request.extensions['timeout']['read'] == 300
        assert request.extensions['paa_model_stream_timeout'] == 300
        assert json.loads(request.content) == {'model': 'wan2.7-image', 'input': {'messages': [{'role': 'user', 'content': [{'text': '画一只鸟'}]}]}, 'parameters': {'n': 1, 'size': expected}}
        return httpx.Response(200, json={'request_id': 'req-sync', 'output': {'choices': [{'message': {'content': [{'image': 'https://image.example/a.png?sign=123'}]}}]}, 'usage': {'input_tokens': 5, 'output_tokens': 8, 'unexpected': 'ignore'}})
    monkeypatch.setattr(wan, 'client', lambda settings: httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    settings = SimpleNamespace(model_allowed_origins=())
    config = {'baseUrl': 'https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1', 'model': 'wan2.7-image', 'protocol': 'dashscope-image'}
    response = await wan.generate_sync(settings, config, 'controlled-token-plan-key', '画一只鸟', size)
    assert response['request_id'] == 'req-sync' and response['usage'] == {'input_tokens': 5, 'output_tokens': 8}
    assert wan.images(response) == ['https://image.example/a.png?sign=123'] and len(calls) == 1
    assert 'task_id' not in response['output']
    with pytest.raises(ProviderError):
        await wan.submit(settings, config, 'controlled-token-plan-key', '画一只鸟')
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('address', ['127.0.0.1', '169.254.169.254', '10.0.0.1', '::1'])
async def test_file_dns_blocks_private_network_even_with_provider_allowlist(monkeypatch, address):
    import asyncio, socket
    async def resolve(*a, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443))]
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', resolve)
    with pytest.raises(ProviderError, match='受限制网络'):
        await CheckedBackend(SimpleNamespace(model_allowed_origins=())).connect_tcp('untrusted.example', 443)


@pytest.mark.asyncio
async def test_download_redirect_checks_and_never_forwards_authorization(monkeypatch):
    seen = []
    real = httpx.AsyncClient
    def handle(request):
        seen.append(request)
        assert 'authorization' not in request.headers and 'cookie' not in request.headers
        if request.url.path == '/start':
            return httpx.Response(302, headers={'location': 'https://other.example/final.png?Expires=123&Signature=signed'})
        return httpx.Response(200, headers={'content-type': 'image/png'}, content=png())
    def client(**kwargs):
        return real(transport=httpx.MockTransport(handle), follow_redirects=False, trust_env=False)
    monkeypatch.setattr(results.httpx, 'AsyncClient', client)
    data, meta = await results.download('https://public.example/start')
    assert data == png() and meta['width'] == 768 and len(seen) == 2
    assert str(seen[-1].url).endswith('?Expires=123&Signature=signed')
    def malicious(request):
        return httpx.Response(302, headers={'location': 'https://169.254.169.254/latest/meta-data'})
    monkeypatch.setattr(results.httpx, 'AsyncClient', lambda **kwargs: real(transport=httpx.MockTransport(malicious)))
    with pytest.raises(ProviderError, match='受限制网络'):
        await results.download('https://public.example/start')


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [404, 410])
async def test_expired_image_url_is_terminal_without_automatic_network_retry(monkeypatch, status):
    real = httpx.AsyncClient
    calls = []
    def expired(request):
        calls.append(request)
        return httpx.Response(status)
    monkeypatch.setattr(results.httpx, 'AsyncClient', lambda **kwargs: real(transport=httpx.MockTransport(expired)))
    with pytest.raises(ProviderError) as error:
        await results.download('https://public.example/image.png')
    assert error.value.code == 'image_expired' and error.value.status == status and len(calls) == 1
