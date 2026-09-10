"""Bounded OpenAI-compatible text transport, shared by checks and minutes."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import socket
import time
import threading
from collections import OrderedDict
from urllib.parse import urlsplit

import httpx

from .repository import DomainError

PROTECTED = {'model', 'messages', 'stream', 'stream_options', 'tools', 'tool_choice', 'functions',
             'function_call', 'response_format', 'n', 'store', 'api_key', 'apikey', 'authorization',
             'headers', 'extra_headers', 'base_url', 'baseurl', 'url', 'endpoint', 'method', 'body',
             'extra_body', 'extra_query', 'query', 'input', 'prompt', 'user', '__proto__', 'prototype', 'constructor'}


def text(value, limit, label, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()) or re.search(r'[\x00-\x1f\x7f]', value):
        raise DomainError('invalid_config', f'{label}无效，请检查长度和特殊字符。')
    return value.strip()


def parameters(value):
    if not isinstance(value, dict) or len(json.dumps(value, ensure_ascii=False).encode()) > 4096:
        raise DomainError('invalid_parameters', '推理参数必须是 4 KiB 以内的 JSON 对象。')
    count = 0
    def visit(item, depth):
        nonlocal count
        if depth > 5:
            raise DomainError('invalid_parameters', '推理参数嵌套不能超过 5 层。')
        if isinstance(item, dict):
            for key, child in item.items():
                count += 1
                if count > 64 or not isinstance(key, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', key) or key.lower() in PROTECTED:
                    raise DomainError('invalid_parameters', '推理参数包含受保护字段或过多字段。')
                visit(child, depth + 1)
        elif isinstance(item, list):
            if len(item) > 32:
                raise DomainError('invalid_parameters', '推理参数数组过长。')
            for child in item:
                visit(child, depth + 1)
        elif isinstance(item, str):
            if len(item) > 512 or re.search(r'[\x00-\x1f\x7f]|\$\{|\{\{|<%|javascript:', item, re.I):
                raise DomainError('invalid_parameters', '推理参数只接受普通 JSON 值，不支持模板或代码。')
        elif item is not None and type(item) not in (bool, int, float):
            raise DomainError('invalid_parameters', '推理参数不是合法 JSON。')
        elif isinstance(item, (int, float)) and (not math.isfinite(item) or abs(item) > 1e12):
            raise DomainError('invalid_parameters', '推理参数数值无效。')
    visit(value, 0)
    return value


def config(value, allow_loopback=False, require_model=True):
    if not isinstance(value, dict) or set(value) != {'profileId', 'revision', 'name', 'baseUrl', 'apiKey', 'model', 'stream', 'parameters'}:
        raise DomainError('invalid_config', '模型服务配置无效。')
    result = dict(value)
    for key, limit in [('profileId', 36), ('revision', 36), ('name', 80), ('baseUrl', 2048), ('apiKey', 4096)]:
        result[key] = text(value[key], limit, key)
    result['model'] = text(value['model'], 256, '模型 ID', empty=not require_model)
    url = urlsplit(result['baseUrl'])
    try:
        valid_port = url.port is None or 1 <= url.port <= 65535
    except ValueError:
        valid_port = False
    if not url.hostname or not valid_port or url.username or url.password or url.query or url.fragment or (url.scheme != 'https' and not (allow_loopback and url.scheme == 'http' and url.hostname in ('127.0.0.1', 'localhost', '::1'))):
        raise DomainError('invalid_url', 'API 地址须为不含用户名、查询参数或片段的 HTTPS Base URL。')
    result['baseUrl'] = result['baseUrl'].rstrip('/')
    if type(value['stream']) is not bool:
        raise DomainError('invalid_config', '传输模式无效。')
    result['parameters'] = parameters(value['parameters'])
    return result


class Limits:
    def __init__(self, connect=10, deadline=180, response=1024 * 1024, request=256 * 1024):
        self.connect, self.deadline, self.response, self.request = connect, deadline, response, request


class _Resolver:
    """One outstanding OS lookup per provider, without an executor shutdown wait."""
    def __init__(self):
        self.lock = threading.Lock()
        self.thread = None

    async def getaddrinfo(self, host, port, *, family=0, type=0, proto=0, flags=0):
        result = {}

        def lookup():
            try:
                result['value'] = socket.getaddrinfo(host, port, family, type, proto, flags)
            except Exception as error:
                result['error'] = error

        with self.lock:
            # An OS resolver cannot be cancelled. Do not accumulate more lookups
            # when its previous caller has timed out; a later manual call can retry.
            if self.thread is not None and self.thread.is_alive():
                raise TimeoutError()
            thread = threading.Thread(target=lookup, name='paa-llm-dns', daemon=True)
            self.thread = thread
            thread.start()

        # No event loop, future, or request credentials enter the DNS thread. A
        # cancelled caller leaves at most one daemon lookup, whose late result is
        # discarded without calling a closed loop; idle threads are not retained.
        while thread.is_alive():
            await asyncio.sleep(.01)
        if 'error' in result:
            raise result['error']
        return result['value']


class Provider:
    def __init__(self, limits=None, allow_loopback=False):
        self.limits = limits or Limits()
        self.allow_loopback = allow_loopback
        self.directory_lock = threading.RLock()
        self.directories = OrderedDict()
        self.resolver = _Resolver()

    @staticmethod
    def directory_scope(settings):
        return (settings['profileId'], settings['baseUrl'], hashlib.sha256(settings['apiKey'].encode()).digest())

    def assert_text_model(self, settings):
        settings = config(settings, self.allow_loopback)
        with self.directory_lock:
            entry = self.directories.get(self.directory_scope(settings))
            if entry and settings['model'] in entry['nontext']:
                raise DomainError('nontext_model', '此模型在该服务目录中明确为非文本模型，不能用于纪要；请选择其他模型或刷新目录。')
        return {'eligible': True}

    def forget_models(self, profile_id):
        with self.directory_lock:
            for scope in list(self.directories):
                if scope[0] == profile_id:
                    del self.directories[scope]

    def payload(self, settings, messages):
        settings = config(settings, self.allow_loopback)
        value = {'model': settings['model'], 'messages': messages, 'stream': settings['stream'], **settings['parameters']}
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        if len(encoded) > self.limits.request:
            raise DomainError('input_too_large', '完整会议文字超出单次请求上限，请选用更适合长会议的处理方案；原文已保留。')
        return encoded

    def request(self, settings, path, body=None, deadline=None, query=None):
        deadline = deadline or time.monotonic() + self.limits.deadline
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DomainError('network_timeout', '服务响应超时，请稍后手动重试。')
        try:
            return asyncio.run(self._request(settings, path, body, query, deadline))
        except (TimeoutError, httpx.TimeoutException):
            raise DomainError('network_timeout', '服务响应超时，请稍后手动重试。') from None
        except (httpx.HTTPError, RuntimeError, OSError):
            if time.monotonic() >= deadline:
                raise DomainError('network_timeout', '服务响应超时，请稍后手动重试。') from None
            raise DomainError('network_error', '无法连接模型服务，请检查地址、网络和证书。') from None

    async def _request(self, settings, path, body, query, deadline):
        # One cancellable task in the existing network worker: each received byte must
        # not restart the total budget, and cancellation closes the awaited socket.
        # This loop belongs only to this request. Keep httpx's original hostname,
        # address selection and TLS verification, but bypass its default DNS executor.
        asyncio.get_running_loop().getaddrinfo = self.resolver.getaddrinfo
        remaining = max(0, deadline - time.monotonic())
        async with asyncio.timeout(remaining):
            timeout = httpx.Timeout(remaining, connect=min(self.limits.connect, remaining))
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
                return await self._read(client, settings, path, body, query, deadline)

    async def _read(self, client, settings, path, body, query, deadline):
        async with client.stream('POST' if body is not None else 'GET', settings['baseUrl'] + path,
                           content=body, params=query,
                           headers={'Authorization': 'Bearer ' + settings['apiKey'], 'Content-Type': 'application/json'}) as response:
            if response.status_code != 200:
                code, message = {
                    401: ('authentication', '密钥无效或已过期，请更新密钥。'),
                    403: ('permission', '当前账号没有权限，请检查服务和模型授权。'),
                    404: ('endpoint', '未找到接口或模型，请检查 Base URL、模型 ID；模型列表不支持时可手动填写。'),
                    429: ('quota', '调用额度或速率受限，请检查余额与限额后重试。'),
                    400: ('request_rejected', '服务拒绝了请求，请检查模型上下文容量、推理参数和传输模式。'),
                }.get(response.status_code, ('provider_error', '模型服务暂不可用，请检查服务状态后重试。'))
                if 300 <= response.status_code < 400:
                    code, message = 'redirect', '服务要求重定向，请直接填写最终 API 地址并重新输入密钥。'
                raise DomainError(code, message)
            content = bytearray()
            async for chunk in response.aiter_bytes():
                if time.monotonic() > deadline:
                    raise DomainError('network_timeout', '服务响应超时，请稍后手动重试。')
                content.extend(chunk)
                if len(content) > self.limits.response:
                    raise DomainError('response_too_large', '服务返回内容过大，请调整模型输出限制。')
            if time.monotonic() > deadline:
                raise DomainError('network_timeout', '服务响应超时，请稍后手动重试。')
            return bytes(content)

    def complete(self, settings, messages):
        settings = config(settings, self.allow_loopback)
        self.assert_text_model(settings)
        data = self.request(settings, '/chat/completions', self.payload(settings, messages))
        try:
            if settings['stream']:
                content, finish, done = [], None, False
                for event in re.split(r'\r?\n\r?\n', data.decode('utf-8')):
                    lines = [line[5:].lstrip() for line in event.splitlines() if line.startswith('data:')]
                    if not lines:
                        continue
                    raw = '\n'.join(lines)
                    if raw == '[DONE]':
                        done = True
                        break
                    item = json.loads(raw)
                    choices = item.get('choices')
                    if choices == []:  # Optional usage event.
                        continue
                    if not isinstance(choices, list) or len(choices) != 1:
                        raise ValueError()
                    choice = choices[0]
                    delta = choice['delta']
                    if delta.get('tool_calls') or delta.get('function_call') or delta.get('refusal'):
                        raise ValueError()
                    part = delta.get('content')
                    if part is not None:
                        if not isinstance(part, str):
                            raise ValueError()
                        content.append(part)
                    if choice.get('finish_reason'):
                        finish = choice['finish_reason']
                if not done or finish != 'stop':
                    raise ValueError()
                result = ''.join(content)
            else:
                payload = json.loads(data)
                choices = payload['choices']
                if not isinstance(choices, list) or len(choices) != 1 or choices[0]['finish_reason'] != 'stop':
                    raise ValueError()
                message = choices[0]['message']
                if message.get('tool_calls') or message.get('function_call') or message.get('refusal'):
                    raise ValueError()
                result = message['content']
            if not isinstance(result, str) or not result.strip():
                raise ValueError()
            return result.strip()
        except (ValueError, TypeError, KeyError, IndexError):
            raise DomainError('invalid_response', '未收到完整有效的文字回复，请检查模型、输出上限及传输模式；本次未自动重试。') from None

    def check(self, settings):
        started = time.monotonic()
        self.complete(settings, [{'role': 'user', 'content': '请只回复：连接成功。'}])
        return {'elapsedMs': round((time.monotonic() - started) * 1000), 'message': '已收到有效回复；自定义参数的实际效果由服务决定。'}

    def models(self, settings):
        settings = config(settings, self.allow_loopback, require_model=False)
        scope, token = self.directory_scope(settings), object()
        with self.directory_lock:
            previous = self.directories.pop(scope, {'nontext': set()})
            self.directories[scope] = {'token': token, 'nontext': previous['nontext']}
            while len(self.directories) > 32:
                self.directories.popitem(last=False)
        result = self._models(settings)
        with self.directory_lock:
            entry = self.directories.get(scope)
            # Deletion or a newer refresh invalidates an in-flight directory response.
            if entry and entry['token'] is token:
                entry['nontext'] = {item['id'] for item in result['models'] if not item['selectable']}
        return result

    def _models(self, settings):
        parsed = urlsplit(settings['baseUrl'])
        alibaba = parsed.hostname in ('dashscope.aliyuncs.com', 'dashscope-intl.aliyuncs.com', 'dashscope-us.aliyuncs.com', 'cn-hongkong.dashscope.aliyuncs.com') or bool(re.fullmatch(r'[a-zA-Z0-9-]+\.(cn-beijing|ap-northeast-1|eu-central-1|us-east-1)\.maas\.aliyuncs\.com', parsed.hostname or ''))
        if alibaba:
            settings = {**settings, 'baseUrl': f'{parsed.scheme}://{parsed.netloc}'}
        deadline, values = time.monotonic() + self.limits.deadline, {}
        for page in range(1, 21):
            raw = self.request(settings, '/api/v1/models' if alibaba else '/models', deadline=deadline,
                               query={'page_no': page, 'page_size': 100} if alibaba else None)
            try:
                payload = json.loads(raw)
                rows = payload['output']['models'] if alibaba else payload['data']
                if not isinstance(rows, list):
                    raise ValueError()
                for row in rows:
                    model = text(row['model' if alibaba else 'id'], 256, '模型 ID')
                    metadata = row.get('inference_metadata')
                    modalities = row.get('output_modalities') or row.get('outputModalities') or (metadata.get('response_modality') if isinstance(metadata, dict) else None)
                    if isinstance(modalities, list):
                        modalities = [str(item).lower() for item in modalities]
                    kind = row.get('type')
                    selectable = not ((isinstance(modalities, list) and modalities and 'text' not in modalities) or kind in ('embedding', 'image', 'audio', 'rerank', 'video'))
                    values[model] = {'id': model, 'selectable': selectable}
                    if len(values) > 2000:
                        raise DomainError('models_too_large', '模型目录超过 2000 项，请手动填写模型 ID。')
                if not alibaba or len(rows) < 100:
                    return {'models': sorted(values.values(), key=lambda item: item['id']), 'updatedAt': time.time()}
            except (ValueError, KeyError, TypeError):
                raise DomainError('invalid_models', '服务未返回兼容的模型列表，可手动填写模型 ID。') from None
        raise DomainError('models_too_large', '模型目录分页超限，请手动填写模型 ID。')
