import json
import logging
import time
from app.integrations.models import transport
from app.integrations.models.diagnostics import http_error, response_metadata as _response_metadata, upstream_error
from app.integrations.models.stream_events import ModelDelta, ToolDelta, tool_arguments
from app.integrations.models.transport import ProviderError, normalize_url, status_error, structured_error, retry_after


log = logging.getLogger(__name__)


def _json_error_metadata(error, scope):
    if not isinstance(error, json.JSONDecodeError):
        return {}
    return {'json_scope': scope, 'json_line': error.lineno, 'json_column': error.colno,
            'json_offset': error.pos, 'json_input_chars': len(error.doc)}


def invalid_response_diagnostic(result, reason, tool_index, on_timing, **metadata):
    """Failure-only shape metadata; never include provider text or arguments."""
    choices = result.get('choices') if isinstance(result, dict) else None
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    message = choice.get('message')
    message = message if isinstance(message, dict) else {}
    content, calls = message.get('content'), message.get('tool_calls')
    finish = choice.get('finish_reason')
    fields = {'reason': reason, 'response_type': type(result).__name__,
              'choices_count': len(choices) if isinstance(choices, list) else None,
              'finish_reason': finish if finish in ('stop', 'tool_calls', 'length', 'content_filter', None) else 'other',
              'body_chars': len(content) if isinstance(content, str) else None,
              'tool_count': len(calls) if isinstance(calls, list) else None,
              **metadata}
    usage = token_usage(result.get('usage')) if isinstance(result, dict) else None
    if usage:
        fields.update(input_tokens=usage.get('prompt_tokens'), output_tokens=usage.get('completion_tokens'))
    if isinstance(calls, list) and tool_index is not None and tool_index < len(calls):
        call = calls[tool_index]
        function = call.get('function') if isinstance(call, dict) else None
        arguments = function.get('arguments') if isinstance(function, dict) else None
        fields.update(tool_index=tool_index, argument_chars=len(arguments) if isinstance(arguments, str) else None)
    if on_timing:
        on_timing('model.invalid_response', **fields)
    else:
        log.warning('model.invalid_response %s', json.dumps(fields, separators=(',', ':')))


def token_usage(value):
    if not isinstance(value, dict):
        return None
    result = {key: count for key, count in value.items() if key in ('prompt_tokens', 'completion_tokens', 'total_tokens') and type(count) is int and 0 <= count <= 1000000000}
    return result or None


async def chat(*args, tool_choice=None, on_timing=None, **kwargs):
    last_progress = None
    original_progress = kwargs.pop('on_progress', None)
    def progress():
        nonlocal last_progress
        if last_progress is None and on_timing:
            on_timing('model.first_progress')
        last_progress = time.monotonic()
        if original_progress:
            original_progress()
    kwargs['on_progress'] = progress
    try:
        async with transport.request_timing(on_timing):
            return await _compatible_chat(*args, tool_choice=tool_choice, on_timing=on_timing, **kwargs)
    finally:
        if last_progress is not None and on_timing:
            on_timing('model.progress.end', elapsed_ms=round((time.monotonic() - last_progress) * 1000, 3))


async def _compatible_chat(*args, tool_choice=None, on_timing=None, on_retry=None, **kwargs):
    try:
        return await _chat(*args, tool_choice=tool_choice, on_timing=on_timing, **kwargs)
    except ProviderError as error:
        if error.code != 'tool_choice_unsupported' or tool_choice != 'required':
            raise
        if on_timing:
            on_timing('model.compatibility', reason='tool_choice_unsupported')
        # Only a provider's explicit parameter rejection permits this one retry;
        # no received content/tool action is replayed and no authorization inferred.
        if on_retry:
            await on_retry(error)
        return await _chat(*args, tool_choice='auto', on_timing=on_timing, **kwargs)


async def _chat(settings, config, key, messages, *, tools=None, tool_choice=None, max_tokens=4000, text_tools=(), on_event=None, on_text=None, on_delta=None, on_progress=None, stream_timeout=None, on_timing=None):
    # The caller may carry prose in designated tools; their output length also
    # follows the provider. Ordinary tool arguments retain their existing cap.
    body = {**config.get('parameters', {}), 'model': config['model'], 'messages': messages, 'stream': config['streaming']}
    if max_tokens is not None:
        body['max_tokens'] = max_tokens
    else:
        for field in ('max_tokens', 'max_completion_tokens', 'max_output_tokens'):
            body.pop(field, None)
    if tools:
        body['tools'] = tools
    if tool_choice:
        body['tool_choice'] = tool_choice
    endpoint = normalize_url(config['baseUrl'], settings) + '/chat/completions'
    if on_event:
        await on_event('started')
    extensions = {'paa_model_streaming': True} if config['streaming'] else {}
    if on_timing:
        async def trace(event, info):
            phases = {'connection.start_tls': 'tls', 'http11.send_request_headers': 'headers_sent',
                      'http11.send_request_body': 'body_sent', 'http11.receive_response_headers': 'response_headers'}
            phase, _, state = event.rpartition('.')
            if phase in phases:
                on_timing('network.' + phases[phase] + '.' + state,
                          **({'error': type(info['exception']).__name__} if 'exception' in info else {}))
        extensions['trace'] = trace
    if config['streaming'] and stream_timeout is not None:
        extensions['paa_model_stream_timeout'] = stream_timeout
    options = {'extensions': extensions} if extensions else {}
    if on_timing:
        on_timing('model.send')
    first_event = False
    first_body = False
    reasoning_started = False
    reasoning_chars = 0
    stream_metadata = {}
    async with transport.client(settings) as http:
        async with http.stream('POST', endpoint, headers={'Authorization': f'Bearer {key}'}, json=body, **options) as response:
            response_metadata = _response_metadata(response)
            if response.is_error:
                await response.aread()
            if response.status_code in (400, 422) and tool_choice == 'required':
                try:
                    detail = response.json().get('error', {})
                    message = str(detail.get('message', '')).lower() if isinstance(detail, dict) else ''
                    if ('tool_choice' in message or 'tool choice' in message) and any(word in message for word in ('unsupported', 'not support', 'invalid', 'required')):
                        raise http_error(ProviderError('tool_choice_unsupported', '服务不支持 required 工具选择', response.status_code),
                                         response, on_timing=on_timing)
                except (ValueError, AttributeError) as error:
                    if isinstance(error, ProviderError):
                        raise
            status_error(response)
            if not config['streaming']:
                await response.aread()
                try:
                    result = response.json()
                except ValueError as error:
                    invalid_response_diagnostic(None, 'response_json', None, on_timing,
                                                **response_metadata, **_json_error_metadata(error, 'response'))
                    raise ProviderError('invalid_response', '模型返回无法解析的内容') from None
                if not isinstance(result, dict):
                    invalid_response_diagnostic(result, 'response_structure', None, on_timing, **response_metadata)
                    raise ProviderError('invalid_response', '模型返回内容结构无效')
                if result.get('error'):
                    error = structured_error(result) or ProviderError('provider_error', '模型服务报告请求失败，请联系管理员查看服务调用记录')
                    raise upstream_error(error, result, source='json', key=key,
                                         metadata=response_metadata, on_timing=on_timing)
                if on_timing and result.get('choices'):
                    on_timing('model.first_event')
                if on_event:
                    await on_event('usage', result.get('usage'))
            else:
                content, calls, finish, done, usage = '', {}, None, False, None
                stream_events = 0
                def stream_diagnostic(reason, **error_metadata):
                    partial = {'choices': [{'message': {'content': content, 'tool_calls': list(calls.values())},
                                            'finish_reason': finish}], 'usage': usage}
                    invalid_response_diagnostic(partial, reason, None, on_timing,
                                                **response_metadata, **error_metadata, stream_events=stream_events,
                                                stream_complete=done, reasoning_chars=reasoning_chars)
                lines = response.aiter_lines()
                async for raw in transport.stream_data(lines):
                    raw = raw.strip()
                    if raw == '[DONE]':
                        done = True
                        if finish:
                            await transport.finish_stream(lines)
                        break
                    stream_events += 1
                    try:
                        part = json.loads(raw)
                    except ValueError as error:
                        stream_diagnostic('stream_json', **_json_error_metadata(error, 'stream_event'))
                        raise ProviderError('invalid_response', '流式接口返回无效数据') from None
                    if not isinstance(part, dict):
                        stream_diagnostic('stream_structure')
                        raise ProviderError('invalid_response', '流式接口返回无效数据')
                    if part.get('error'):
                        error = structured_error(part, delay=retry_after(response)) or ProviderError('provider_error', '模型服务报告流式请求失败，请联系管理员查看服务调用记录')
                        raise upstream_error(error, part, source='sse', key=key,
                                             metadata=response_metadata, on_timing=on_timing)
                    if part.get('usage'):
                        usage = part['usage']
                        if on_event:
                            await on_event('usage', usage)
                    choices = part.get('choices', [])
                    if not choices:
                        continue
                    if not isinstance(choices, list):
                        stream_diagnostic('stream_choices_structure')
                        raise ProviderError('invalid_response', '流式接口返回无效数据')
                    item = choices[0]
                    if not isinstance(item, dict) or not isinstance(item.get('delta', {}), dict):
                        stream_diagnostic('stream_delta_structure')
                        raise ProviderError('invalid_response', '流式接口返回无效数据')
                    if item.get('finish_reason') == 'content_filter':
                        raise upstream_error(structured_error({'code': 'content_filter'}), {'finish_reason': 'content_filter'},
                                             source='sse', key=key, metadata=response_metadata, on_timing=on_timing)
                    delta = item.get('delta', {})
                    if not first_event and (delta.get('content') or delta.get('tool_calls') or delta.get('reasoning_content') or item.get('finish_reason')):
                        if on_timing:
                            on_timing('model.first_event')
                        first_event = True
                    fragment_text = delta.get('content') or ''
                    if not isinstance(fragment_text, str):
                        stream_diagnostic('content_type')
                        raise ProviderError('invalid_response', '模型正文无效')
                    if fragment_text.strip() and not first_body:
                        first_body = True
                        if on_timing:
                            on_timing('model.first_body')
                    content += fragment_text
                    fragments = []
                    tool_fragments = delta.get('tool_calls') or []
                    if not isinstance(tool_fragments, list):
                        stream_diagnostic('tool_calls_structure')
                        raise ProviderError('invalid_response', '工具调用分片无效')
                    for fragment in tool_fragments:
                        if not isinstance(fragment, dict):
                            stream_diagnostic('tool_fragment_structure')
                            raise ProviderError('invalid_response', '工具调用分片无效')
                        index = fragment.get('index')
                        if not isinstance(index, int) or not 0 <= index < 16:
                            stream_diagnostic('tool_call_index')
                            raise ProviderError('invalid_response', '工具调用序号无效')
                        if not isinstance(fragment.get('function', {}), dict):
                            stream_diagnostic('tool_function')
                            raise ProviderError('invalid_response', '工具调用分片无效')
                        values = [fragment.get('id') or '', fragment.get('function', {}).get('name') or '', fragment.get('function', {}).get('arguments') or '']
                        if any(not isinstance(value, str) for value in values):
                            stream_diagnostic('tool_fragment_type')
                            raise ProviderError('invalid_response', '工具调用分片无效')
                        fragments.append(ToolDelta(index, values[1], values[2], values[0]))
                        call = calls.setdefault(index, {'id': '', 'type': 'function', 'function': {'name': '', 'arguments': ''}})
                        call['id'] += fragment.get('id') or ''
                        call['function']['name'] += fragment.get('function', {}).get('name') or ''
                        call['function']['arguments'] += fragment.get('function', {}).get('arguments') or ''
                        if len(call['id']) > 200 or len(call['function']['name']) > 80 or (call['function']['name'] not in text_tools and len(call['function']['arguments']) > 32000):
                            stream_diagnostic('tool_fragment_size')
                            raise ProviderError('invalid_response', '工具调用无效或过长')
                    # Reasoning only signals activity; its contents never enter
                    # callbacks, replies, usage records or persisted node output.
                    reasoning = delta.get('reasoning_content')
                    if isinstance(reasoning, str):
                        reasoning_chars += len(reasoning)
                    if on_progress and (fragment_text.strip() or any(fragment.arguments.strip() for fragment in fragments) or isinstance(reasoning, str) and reasoning.strip()):
                        on_progress()
                    thinking = not reasoning_started and isinstance(reasoning, str) and bool(reasoning.strip())
                    reasoning_started = reasoning_started or thinking
                    if on_delta and (fragment_text or fragments or thinking):
                        await on_delta(ModelDelta(fragment_text, tuple(fragments), thinking))
                    if on_text and (fragment_text or delta.get('tool_calls')):
                        await on_text(content, bool(calls))
                    if item.get('finish_reason'):
                        finish = item['finish_reason']
                if not done or not finish:
                    stream_diagnostic('stream_incomplete')
                    raise ProviderError('interrupted', '流式响应未完整结束，已停止执行；请核对后重试')
                result = {'choices': [{'message': {'role': 'assistant', 'content': content, 'tool_calls': [calls[i] for i in sorted(calls)]}, 'finish_reason': finish}], 'usage': usage or {}}
                stream_metadata = {'stream_complete': done, 'reasoning_chars': reasoning_chars, 'stream_events': stream_events}
    if on_timing:
        on_timing('model.received', **response_metadata, **stream_metadata)
    reason, tool_index = 'choices_structure', None
    try:
        choice = result['choices'][0]
        reason = 'choice_structure'
        if choice.get('finish_reason') == 'content_filter':
            raise upstream_error(structured_error({'code': 'content_filter'}), {'finish_reason': 'content_filter'},
                                 source='json', key=key, metadata=response_metadata, on_timing=on_timing)
        if choice.get('finish_reason') not in ('stop', 'tool_calls'):
            invalid_response_diagnostic(result, 'finish_reason', None, on_timing, **response_metadata, **stream_metadata)
            raise ProviderError('invalid_response', '模型响应未正常完成或达到输出限制', output_limit=choice.get('finish_reason') == 'length')
        reason = 'message_structure'
        message = choice['message']
        reason = 'content_type'
        if not isinstance(message.get('content') or '', str):
            raise ValueError()
        calls = message.get('tool_calls') or []
        reason = 'tool_calls_structure'
        if not isinstance(calls, list):
            raise ValueError()
        reason = 'too_many_tool_calls'
        if len(calls) > 16:
            raise ValueError()
        reason = 'empty_response'
        if not calls and not (message.get('content') or '').strip():
            raise ValueError()
        for tool_index, call in enumerate(calls):
            reason = 'tool_call_id'
            if not call['id'] or len(call['id']) > 200:
                raise ValueError()
            reason = 'tool_function'
            if not call['function']['name'] or len(call['function']['name']) > 80:
                raise ValueError()
            reason = 'tool_arguments_size'
            if call['function']['name'] not in text_tools and len(call['function']['arguments']) > 32000:
                raise ValueError()
            reason = 'tool_arguments_json'
            try:
                arguments = tool_arguments(call['function']['arguments'])
            except json.JSONDecodeError:
                raise
            except ValueError as error:
                reason = {'Duplicate JSON key': 'tool_arguments_duplicate_key',
                          'Invalid JSON constant': 'tool_arguments_nonfinite'}.get(str(error), 'tool_arguments_json')
                raise
            reason = 'tool_arguments_object'
            if not isinstance(arguments, dict):
                raise ValueError()
        result['usage'] = token_usage(result.get('usage')) or {}
        if on_timing:
            on_timing('model.usage', input_tokens=result['usage'].get('prompt_tokens'), output_tokens=result['usage'].get('completion_tokens'))
        return result
    except ProviderError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as error:
        invalid_response_diagnostic(result, reason, tool_index, on_timing,
                                    **response_metadata, **stream_metadata, **_json_error_metadata(error, 'tool_arguments'))
        raise ProviderError('invalid_response', '模型未返回完整文字或有效工具调用') from None
