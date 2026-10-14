"""DashScope-compatible image adapters; creation never auto-retries or falls back."""
import asyncio
import httpx
import re
from urllib.parse import urlsplit
from .profiles import api_mode
from .sizes import wire_size
from app.integrations.models.transport import ProviderError, client, normalize_url, safe_error, status_error, structured_error


def endpoint(settings, config):
    url = normalize_url(config['baseUrl'], settings)
    parts = urlsplit(url)
    origin = f'{parts.scheme}://{parts.netloc}'
    if config['protocol'] != 'dashscope-image':
        raise ProviderError('protocol', '请选择图片生成接口', sent=False)
    api_mode(config)
    if parts.path not in ('', '/api/v1', '/compatible-mode/v1'):
        raise ProviderError('address', '图片服务地址请填写兼容服务域名、/api/v1 或 /compatible-mode/v1 根地址', sent=False)
    return origin + '/api/v1'


def synchronous(config):
    return api_mode(config) == 'multimodal-sync'


async def request(settings, config, key, method, path, body=None, *, sync=False):
    url = endpoint(settings, config) + path
    headers = {'Authorization': 'Bearer ' + key}
    if method == 'POST' and not sync:
        headers['X-DashScope-Async'] = 'enable'
    options = {'timeout': httpx.Timeout(300, connect=10), 'extensions': {'paa_model_stream_timeout': 300}} if sync else {}
    try:
        async with client(settings) as http:
            response = await http.request(method, url, json=body, headers=headers, **options)
            status_error(response)
            result = response.json()
        if not isinstance(result, dict):
            raise ValueError()
        error = structured_error(result)
        if error:
            raise error
        return result
    except Exception as error:
        raise safe_error(error) from None


async def submit(settings, config, key, prompt, size=None):
    if synchronous(config):
        raise ProviderError('protocol', '此图片配置使用同步多模态接口', sent=False)
    params = {'n': 1}
    size = wire_size(config, size)
    if config['model'] in ('wan2.7-image', 'wan2.7-image-pro'):
        params['enable_sequential'] = False
    if size:
        params['size'] = size
    result = await request(settings, config, key, 'POST', '/services/aigc/image-generation/generation', {'model': config['model'], 'input': {'messages': [{'role': 'user', 'content': [{'text': prompt}]}]}, 'parameters': params})
    task_id = result.get('output', {}).get('task_id')
    if not isinstance(task_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', task_id):
        raise ProviderError('image_unknown', '图片请求已发出，但未取得可恢复的任务编号；请勿重复生成。')
    return task_id, str(result.get('request_id', ''))[:200]


async def generate_sync(settings, config, key, prompt, size=None):
    if not synchronous(config):
        raise ProviderError('protocol', '此图片服务使用异步生成接口', sent=False)
    size = wire_size(config, size)
    params = {'n': 1}
    if size:
        params['size'] = size
    body = {'model': config['model'], 'input': {'messages': [{'role': 'user', 'content': [{'text': prompt}]}]}, 'parameters': params}
    async with asyncio.timeout(300):
        result = await request(settings, config, key, 'POST', '/services/aigc/multimodal-generation/generation', body, sync=True)
    # Persist only useful external facts; do not retain arbitrary response prose.
    usage = result.get('usage')
    usage = {k: v for k, v in usage.items() if k in ('input_tokens', 'output_tokens', 'total_tokens') and type(v) is int and v >= 0} if isinstance(usage, dict) else {}
    return {'output': {'choices': [{'message': {'content': [{'image': url} for url in images(result)]}}]},
        'usage': usage, 'request_id': str(result.get('request_id', ''))[:200]}


async def query(settings, config, key, task_id):
    if synchronous(config):
        raise ProviderError('protocol', '同步图片结果不使用异步任务查询', sent=False)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', task_id):
        raise ProviderError('invalid_response', '图片任务编号无效')
    result = await request(settings, config, key, 'GET', '/tasks/' + task_id)
    output = result.get('output', {})
    if not isinstance(output, dict) or output.get('task_status') not in ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELED', 'UNKNOWN'):
        raise ProviderError('invalid_response', '图片任务返回了无法识别的状态')
    return result


def images(result):
    output = result.get('output', {})
    urls = []
    choices = output.get('choices') if isinstance(output, dict) else None
    for choice in choices if isinstance(choices, list) else []:
        if not isinstance(choice, dict):
            continue
        message = choice.get('message', {})
        contents = message.get('content') if isinstance(message, dict) else None
        for content in contents if isinstance(contents, list) else []:
            if isinstance(content, dict) and isinstance(content.get('image'), str):
                urls.append(content['image'])
    return list(dict.fromkeys(urls))[:4]
