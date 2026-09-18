"""Finite model protocols over DNS-pinned, bounded server-side HTTP."""
import asyncio
import base64
import io
import ipaddress
import json
import re
import socket
import time
from urllib.parse import urlsplit, urlunsplit

import httpx
from httpcore._backends.auto import AutoBackend
from PIL import Image

from .model_schemas import parameters


class ProviderError(ValueError):
    def __init__(self, code, message, status=None):
        super().__init__(message)
        self.code, self.status = code, status


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
            raise ProviderError('network', '无法连接模型服务，请检查地址和网络') from None


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
        raise ProviderError('quota', '服务额度不足或请求受限，请查看服务商账户', code)
    if code in (400, 404, 405, 415, 422):
        raise ProviderError('protocol', '服务不支持当前路径、模型或参数，请核对接口配置', code)
    if 300 <= code < 400:
        raise ProviderError('address', '服务返回重定向，请直接填写最终服务地址', code)
    raise ProviderError('network', '模型服务暂不可用，请稍后手动重试', code)


def safe_error(error):
    if isinstance(error, ProviderError):
        return error
    if isinstance(error, (asyncio.TimeoutError, httpx.TimeoutException)):
        return ProviderError('timeout', '请求超时，可能已产生调用费用；请核对后再重试')
    if isinstance(error, httpx.HTTPError):
        return ProviderError('network', '模型连接中断，请检查网络并核对调用记录')
    return ProviderError('invalid_response', '模型返回内容不符合所选接口，请核对模型能力与参数')


def token_usage(value):
    if not isinstance(value, dict):
        return None
    result = {key: count for key, count in value.items() if key in ('prompt_tokens', 'completion_tokens', 'total_tokens') and type(count) is int and 0 <= count <= 1000000000}
    return result or None


def request_options(model, preset_id=None):
    selected = model.get('selectedPresetId') if preset_id is None else preset_id
    preset = next((p for p in model.get('presets', []) if p['id'] == selected), None)
    if selected and not preset:
        raise ProviderError('protocol', '选择的推理预设不存在')
    return parameters(({'reasoning_effort': preset['value']} if preset['mode'] == 'simple' else preset['parameters']) if preset else {})


async def catalog(settings, base_url, key):
    base_url = normalize_url(base_url, settings)
    parsed = urlsplit(base_url)
    # Token Plan shares the workspace hostname pattern, but exposes the OpenAI
    # catalog at the configured base URL instead of DashScope's /api/v1/models.
    official = parsed.hostname != 'token-plan.cn-beijing.maas.aliyuncs.com' and (parsed.hostname in ('dashscope.aliyuncs.com', 'dashscope-intl.aliyuncs.com', 'dashscope-us.aliyuncs.com', 'cn-hongkong.dashscope.aliyuncs.com') or bool(re.fullmatch(r'[a-zA-Z0-9-]+\.(cn-beijing|ap-northeast-1|eu-central-1|us-east-1)\.maas\.aliyuncs\.com', parsed.hostname or '')))
    endpoint = f'{parsed.scheme}://{parsed.netloc}/api/v1/models' if official else base_url + '/models'
    ids, size, deadline = [], 0, time.monotonic() + 30
    async with client(settings) as http:
        for page in range(1, 21):
            response = await asyncio.wait_for(http.get(endpoint, params={'page_no': page, 'page_size': 100} if official else None, headers={'Authorization': f'Bearer {key}'}), max(0.01, deadline - time.monotonic()))
            status_error(response)
            size += len(response.content)
            if size > 2 * 1024 * 1024:
                raise ProviderError('limit', '模型目录超过 2 MiB，请手动填写模型 ID')
            data = response.json()
            entries = data.get('output', {}).get('models') if official else data.get('data')
            if not isinstance(entries, list) or len(entries) > 2000:
                raise ProviderError('invalid_response', '模型目录格式无效或超过 2000 项，请手动填写模型 ID')
            field = 'model' if official else 'id'
            ids.extend(x[field] for x in entries if isinstance(x, dict) and isinstance(x.get(field), str) and 0 < len(x[field]) <= 200 and all(ord(c) >= 32 for c in x[field]))
            ids = list(dict.fromkeys(ids))
            if len(ids) > 2000:
                raise ProviderError('limit', '模型目录超过 2000 项，请手动填写模型 ID')
            if not official or len(entries) < 100:
                return {'models': ids, 'source': endpoint, 'truncated': bool(data.get('has_more'))}
    raise ProviderError('limit', '模型目录超过分页上限，请手动填写模型 ID')


def reply_review_config(config):
    """Use a non-thinking review only where the provider protocol is known.

    Keep the frozen user configuration intact. Unknown gateways/models retain
    their parameters; OpenAI compatibility alone does not imply thinking support.
    """
    host = urlsplit(config['baseUrl']).hostname or ''
    model = config['model'].lower()
    aliyun = host in ('dashscope.aliyuncs.com', 'dashscope-intl.aliyuncs.com', 'dashscope-us.aliyuncs.com', 'cn-hongkong.dashscope.aliyuncs.com', 'token-plan.cn-beijing.maas.aliyuncs.com') or bool(re.fullmatch(r'[a-zA-Z0-9-]+\.(cn-beijing|ap-northeast-1|eu-central-1|us-east-1)\.maas\.aliyuncs\.com', host))
    hybrid_deepseek = bool(re.fullmatch(r'deepseek-v(?:3\.[12](?:-exp)?|4(?:\.1)?-(?:pro|flash)(?:-\d{4})?)', model))
    toggle = None
    # https://help.aliyun.com/zh/model-studio/deep-thinking
    if aliyun and hybrid_deepseek:
        toggle = {'enable_thinking': False}
    # https://api-docs.deepseek.com/guides/thinking_mode/
    elif host == 'api.deepseek.com' and (model == 'deepseek-chat' or hybrid_deepseek):
        toggle = {'thinking': {'type': 'disabled'}}
    if toggle is None:
        return config
    options = {key: value for key, value in config.get('parameters', {}).items() if key not in ('enable_thinking', 'thinking', 'thinking_budget', 'reasoning_effort')}
    return {**config, 'parameters': {**options, **toggle}}


async def chat(settings, config, key, messages, *, tools=None, tool_choice=None, max_tokens=4000, on_event=None, on_text=None):
    body = {**config.get('parameters', {}), 'model': config['model'], 'messages': messages, 'stream': config['streaming'], 'max_tokens': max_tokens}
    if tools:
        body['tools'] = tools
    if tool_choice:
        body['tool_choice'] = tool_choice
    endpoint = normalize_url(config['baseUrl'], settings) + '/chat/completions'
    if on_event:
        await on_event('started')
    async with client(settings) as http:
        async with http.stream('POST', endpoint, headers={'Authorization': f'Bearer {key}'}, json=body) as response:
            status_error(response)
            if not config['streaming']:
                await response.aread()
                result = response.json()
                if on_event:
                    await on_event('usage', result.get('usage'))
            else:
                content, calls, finish, done, usage = '', {}, None, False, None
                async for line in response.aiter_lines():
                    if not line.startswith('data:'):
                        continue
                    raw = line[5:].strip()
                    if raw == '[DONE]':
                        done = True
                        break
                    try:
                        part = json.loads(raw)
                    except ValueError:
                        raise ProviderError('invalid_response', '流式接口返回无效数据') from None
                    if part.get('error'):
                        raise ProviderError('protocol', '流式接口报告请求失败，请核对模型参数')
                    if part.get('usage'):
                        usage = part['usage']
                        if on_event:
                            await on_event('usage', usage)
                    choices = part.get('choices', [])
                    if not choices:
                        continue
                    item = choices[0]
                    delta = item.get('delta', {})
                    fragment_text = delta.get('content') or ''
                    if not isinstance(fragment_text, str) or len(content) + len(fragment_text) > 32000:
                        raise ProviderError('invalid_response', '模型正文无效或过长')
                    content += fragment_text
                    for fragment in delta.get('tool_calls') or []:
                        index = fragment.get('index')
                        if not isinstance(index, int) or not 0 <= index < 16:
                            raise ProviderError('invalid_response', '工具调用序号无效')
                        call = calls.setdefault(index, {'id': '', 'type': 'function', 'function': {'name': '', 'arguments': ''}})
                        call['id'] += fragment.get('id') or ''
                        call['function']['name'] += fragment.get('function', {}).get('name') or ''
                        call['function']['arguments'] += fragment.get('function', {}).get('arguments') or ''
                    if on_text and (fragment_text or delta.get('tool_calls')):
                        await on_text(content, bool(calls))
                    if item.get('finish_reason'):
                        finish = item['finish_reason']
                if not done or not finish:
                    raise ProviderError('interrupted', '流式响应未完整结束，已停止执行；请核对后重试')
                result = {'choices': [{'message': {'role': 'assistant', 'content': content, 'tool_calls': [calls[i] for i in sorted(calls)]}, 'finish_reason': finish}], 'usage': usage or {}}
    try:
        choice = result['choices'][0]
        if choice.get('finish_reason') not in ('stop', 'tool_calls'):
            raise ProviderError('invalid_response', '模型响应未正常完成或达到输出限制')
        message = choice['message']
        if not isinstance(message.get('content') or '', str) or len(message.get('content') or '') > 32000:
            raise ValueError()
        calls = message.get('tool_calls') or []
        if len(calls) > 16 or (not calls and not (message.get('content') or '').strip()):
            raise ValueError()
        for call in calls:
            if not call['id'] or len(call['id']) > 200 or not call['function']['name'] or len(call['function']['name']) > 80 or len(call['function']['arguments']) > 32000 or not isinstance(json.loads(call['function']['arguments']), dict):
                raise ValueError()
        result['usage'] = token_usage(result.get('usage')) or {}
        return result
    except ProviderError:
        raise
    except (KeyError, TypeError, ValueError, IndexError):
        raise ProviderError('invalid_response', '模型未返回完整文字或有效工具调用') from None


def dashscope_asr_endpoint(base):
    # Keep the configured origin and any gateway prefix. Native ASR can share
    # a service's OpenAI-compatible Base URL, without another host or API key.
    if base.endswith('/compatible-mode/v1'):
        base = base[:-len('/compatible-mode/v1')] + '/api/v1'
    elif not urlsplit(base).path:
        base += '/api/v1'
    return base + '/services/aigc/multimodal-generation/generation'


def dashscope_asr_text(data):
    # Token Plan returns text directly; DashScope may wrap it in output.
    for _ in range(3):
        if not isinstance(data, dict):
            break
        if isinstance(data.get('text'), str):
            return data['text']
        sentence = data.get('sentence')
        if isinstance(sentence, dict) and isinstance(sentence.get('text'), str):
            return sentence['text']
        data = data.get('output')
    return None


async def transcribe(settings, config, key, wav, *, on_event=None):
    if len(wav) > 6 * 1024 * 1024:
        raise ProviderError('limit', '规范化语音超过上传限制，请缩短语音')
    base = normalize_url(config['baseUrl'], settings)
    if urlsplit(base).hostname == 'token-plan.cn-beijing.maas.aliyuncs.com':
        model = config['model']
        if re.fullmatch(r'qwen3-asr-flash(?:-.*)?', model) or model == 'qwen-audio-3.0-asr-flash-streaming':
            raise ProviderError('protocol', 'Token Plan 的语音识别请配置 qwen-audio-3.0-asr-flash，并选择阿里原生语音转写接口；修改后点击“使用当前配置重新处理”')
        if re.fullmatch(r'qwen-audio-3\.0-asr-flash(?:-\d{4}-\d{2}-\d{2})?', model) and config['protocol'] != 'dashscope-asr':
            raise ProviderError('protocol', '此 Token Plan 语音模型需要阿里原生语音转写接口；修改后点击“使用当前配置重新处理”')
    if on_event:
        await on_event('started')
    async with client(settings) as http:
        headers = {'Authorization': f'Bearer {key}'}
        if config['protocol'] == 'transcriptions':
            fields = {'model': config['model'], 'response_format': 'json'}
            if config.get('language'):
                fields['language'] = config['language']
            response = await http.post(base + '/audio/transcriptions', headers=headers, data=fields, files={'file': ('speech.wav', wav, 'audio/wav')})
        elif config['protocol'] == 'dashscope-asr':
            if config.get('language'):
                raise ProviderError('protocol', '阿里原生语音转写使用自动语言识别，请清空识别语言')
            body = {
                'model': config['model'],
                'input': {'messages': [{'role': 'user', 'content': [{'type': 'input_audio', 'input_audio': {'data': 'data:audio/wav;base64,' + base64.b64encode(wav).decode()}}]}]},
                'parameters': {'format': 'wav', 'sample_rate': '16000'},
            }
            response = await http.post(dashscope_asr_endpoint(base), headers={**headers, 'X-DashScope-SSE': 'disable'}, json=body)
        elif config['protocol'] == 'qwen-asr':
            body = {'model': config['model'], 'messages': [{'role': 'user', 'content': [{'type': 'input_audio', 'input_audio': {'data': 'data:audio/wav;base64,' + base64.b64encode(wav).decode()}}]}], 'stream': False}
            if config.get('language'):
                body['asr_options'] = {'language': config['language']}
            response = await http.post(base + '/chat/completions', headers=headers, json=body)
        else:
            raise ProviderError('protocol', '请选择支持的语音转写协议')
        status_error(response)
        data = response.json()
        if on_event:
            await on_event('usage', data.get('usage'))
        if config['protocol'] == 'dashscope-asr':
            text = dashscope_asr_text(data)
        elif config['protocol'] == 'transcriptions':
            text = data.get('text')
        else:
            text = data['choices'][0]['message']['content']
        if not isinstance(text, str) or not text.strip() or len(text) > 8000:
            raise ProviderError('invalid_response', '语音接口没有返回有效文字')
        return text, token_usage(data.get('usage'))


def image_sample():
    image = Image.new('RGB', (64, 64), (255, 0, 0))
    data = io.BytesIO()
    image.save(data, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(data.getvalue()).decode()
