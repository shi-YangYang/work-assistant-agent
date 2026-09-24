import json
from app.integrations.models import transport
from app.integrations.models.transport import ProviderError, normalize_url, status_error


def token_usage(value):
    if not isinstance(value, dict):
        return None
    result = {key: count for key, count in value.items() if key in ('prompt_tokens', 'completion_tokens', 'total_tokens') and type(count) is int and 0 <= count <= 1000000000}
    return result or None


async def chat(settings, config, key, messages, *, tools=None, tool_choice=None, max_tokens=4000, on_event=None, on_text=None):
    body = {**config.get('parameters', {}), 'model': config['model'], 'messages': messages, 'stream': config['streaming'], 'max_tokens': max_tokens}
    if tools:
        body['tools'] = tools
    if tool_choice:
        body['tool_choice'] = tool_choice
    endpoint = normalize_url(config['baseUrl'], settings) + '/chat/completions'
    if on_event:
        await on_event('started')
    async with transport.client(settings) as http:
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
