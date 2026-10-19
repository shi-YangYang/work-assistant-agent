"""Validation failures expose bounded metadata without changing successful replies."""
import copy
import json
import logging
from types import SimpleNamespace

import httpx
import pytest

from app.integrations.models.chat import chat
from app.integrations.models.transport import ProviderError
from app.tasks.timing import Timing
from _support.agent.model_stream_errors import client_for, stream

pytestmark = pytest.mark.asyncio
SECRET = 'private-user-content-do-not-log'
CONFIG = {'baseUrl': 'https://example.com/v1', 'model': 'controlled', 'streaming': False, 'parameters': {}}


def response(content='', calls=None):
    return {'choices': [{'message': {'content': content, 'tool_calls': calls or []}, 'finish_reason': 'stop'}]}


def call(arguments='{}', **overrides):
    return {'id': SECRET, 'function': {'name': SECRET, 'arguments': arguments}, **overrides}


@pytest.mark.parametrize(('payload', 'reason'), [
    ({}, 'choices_structure'),
    ({'choices': []}, 'choices_structure'),
    ({'choices': [None]}, 'choice_structure'),
    ({'choices': [{'finish_reason': 'stop'}]}, 'message_structure'),
    (response([SECRET]), 'content_type'),
    (response(calls='invalid'), 'tool_calls_structure'),
    (response(calls=[call()] * 17), 'too_many_tool_calls'),
    (response(), 'empty_response'),
    (response(calls=[call(id='')]), 'tool_call_id'),
    (response(calls=[call(function={})]), 'tool_function'),
    (response(calls=[call('x' * 32001)]), 'tool_arguments_size'),
    (response(calls=[call('{"secret":"' + SECRET + '"')]), 'tool_arguments_json'),
    (response(calls=[call('{"secret":1,"secret":2}')]), 'tool_arguments_duplicate_key'),
    (response(calls=[call('{"secret":NaN}')]), 'tool_arguments_nonfinite'),
    (response(calls=[call('["' + SECRET + '"]')]), 'tool_arguments_object'),
])
async def test_invalid_response_records_reason_and_no_content(monkeypatch, caplog, payload, reason):
    client_for(monkeypatch, lambda _: httpx.Response(200, json=payload))
    caplog.set_level(logging.INFO)
    timing = Timing('diagnostic-test')
    with pytest.raises(ProviderError) as failure:
        await chat(SimpleNamespace(model_allowed_origins=()), CONFIG, SECRET,
                   [{'role': 'user', 'content': SECRET}], on_timing=timing.mark)
    assert failure.value.code == 'invalid_response'
    assert str(failure.value) == '模型未返回完整文字或有效工具调用'
    entries = [json.loads(record.message.removeprefix('latency ')) for record in caplog.records
               if record.name == 'paa.latency' and 'model.invalid_response' in record.message]
    assert len(entries) == 1 and entries[0]['reason'] == reason
    assert entries[0]['job'] == 'diagnostic-test' and entries[0]['response_type'] == 'dict'
    assert SECRET not in caplog.text and SECRET not in str(failure.value)


@pytest.mark.parametrize('streaming', [False, True])
async def test_stream_and_json_keep_the_same_diagnostic_metadata(monkeypatch, caplog, streaming):
    arguments = '{"private":"' + SECRET + '","private":2}'
    tool = {**call(arguments), 'index': 0}
    client_for(monkeypatch, lambda _: stream({'choices': [{'delta': {'tool_calls': [tool]}, 'finish_reason': 'tool_calls'}]})
               if streaming else httpx.Response(200, json=response(calls=[tool])))
    with pytest.raises(ProviderError):
        await chat(SimpleNamespace(model_allowed_origins=()), {**CONFIG, 'streaming': streaming}, SECRET, [])
    records = [r for r in caplog.records if r.message.startswith('model.invalid_response ')]
    assert len(records) == 1
    metadata = json.loads(records[0].message.removeprefix('model.invalid_response '))
    assert metadata['reason'] == 'tool_arguments_duplicate_key'
    assert metadata['argument_chars'] == len(arguments) and metadata['tool_index'] == 0
    assert metadata['body_chars'] == 0 and metadata['tool_count'] == 1
    assert SECRET not in caplog.text


@pytest.mark.parametrize('streaming', [False, True])
@pytest.mark.parametrize('tools', [False, True])
async def test_success_is_unchanged_and_does_not_emit_diagnostics(monkeypatch, caplog, streaming, tools):
    expected = response(content=SECRET, calls=[{**call('{"number":3}'), 'index': 0, 'type': 'function'}] if tools else [])
    payload = copy.deepcopy(expected)
    if streaming:
        choice = payload['choices'][0]
        choice['delta'] = choice.pop('message')
    calls, events = [], []
    def respond(request):
        calls.append(request)
        return stream(payload) if streaming else httpx.Response(200, json=payload)
    client_for(monkeypatch, respond)
    actual = await chat(SimpleNamespace(model_allowed_origins=()), {**CONFIG, 'streaming': streaming}, SECRET, [],
                        on_timing=lambda event, **fields: events.append((event, fields)))
    message = actual['choices'][0]['message']
    assert message['content'] == SECRET
    assert len(message.get('tool_calls') or []) == int(tools)
    if tools:
        assert message['tool_calls'][0]['function']['arguments'] == '{"number":3}'
    assert len(calls) == 1
    assert not any(event == 'model.invalid_response' for event, _ in events)
    assert not caplog.records


@pytest.mark.parametrize('finish,done,expected_code,reason', [
    ('length', True, 'invalid_response', 'finish_reason'),
    ('unknown', True, 'invalid_response', 'finish_reason'),
    ('stop', False, 'interrupted', 'stream_incomplete'),
    (None, True, 'interrupted', 'stream_incomplete'),
])
async def test_stream_termination_has_shape_evidence_without_reasoning(monkeypatch, caplog, finish, done, expected_code, reason):
    payload = {'choices': [{'delta': {'content': SECRET, 'reasoning_content': SECRET}, 'finish_reason': finish}],
               'usage': {'prompt_tokens': 12, 'completion_tokens': 34, 'private': SECRET}}
    requests = []
    def respond(request):
        requests.append(request)
        return stream(payload, done=done)
    client_for(monkeypatch, respond)
    caplog.set_level(logging.INFO, logger='paa.latency')
    timing = Timing('stream-diagnostic', 2, 3)
    with pytest.raises(ProviderError) as caught:
        with timing.span('model', call='stream-call', kind='main'):
            await chat(SimpleNamespace(model_allowed_origins=()), {**CONFIG, 'streaming': True}, SECRET, [],
                       on_timing=timing.mark)
    assert caught.value.code == expected_code and len(requests) == 1
    failures = diagnostic_entries(caplog)
    assert len(failures) == 1
    info = failures[0]
    assert info['reason'] == reason and info['stream_complete'] == done
    assert info['body_chars'] == info['reasoning_chars'] == len(SECRET)
    assert info['finish_reason'] == ('other' if finish == 'unknown' else finish)
    assert info['input_tokens'] == 12 and info['output_tokens'] == 34
    assert info['stream_events'] == 1 and info['http_status'] == 200
    assert info['content_type'] == 'text/event-stream' and info['parent_call'] == 'stream-call'
    assert info['job'] == 'stream-diagnostic' and info['attempt'] == 2 and info['fence'] == 3
    assert SECRET not in caplog.text


@pytest.mark.parametrize('payload,reason', [
    ({'choices': 'private-invalid-shape'}, 'stream_choices_structure'),
    ({'choices': [{'delta': {'tool_calls': [None]}}]}, 'tool_fragment_structure'),
    ({'choices': [{'delta': {'tool_calls': SECRET}}]}, 'tool_calls_structure'),
])
async def test_invalid_stream_shapes_use_same_failure_contract(monkeypatch, payload, reason):
    client_for(monkeypatch, lambda _: stream(payload))
    events = []
    with pytest.raises(ProviderError) as caught:
        await chat(SimpleNamespace(model_allowed_origins=()), {**CONFIG, 'streaming': True}, SECRET, [],
                   on_timing=lambda event, **fields: events.append((event, fields)))
    assert caught.value.code == 'invalid_response'
    failures = [fields for event, fields in events if event == 'model.invalid_response']
    assert len(failures) == 1 and failures[0]['reason'] == reason
    assert SECRET not in json.dumps(events)


def diagnostic_entries(caplog, event='model.invalid_response'):
    return [value for row in caplog.records if row.name == 'paa.latency'
            and (value := json.loads(row.message.removeprefix('latency ')))['event'] == event]


@pytest.mark.parametrize('scope', ['response', 'stream_event', 'tool_arguments'])
async def test_json_location_and_safe_response_metadata_survive_timing(monkeypatch, caplog, scope):
    raw = '{"private":"' + SECRET + '",'
    if scope != 'stream_event':
        raw += '\n'
    headers = {'content-type': 'APPLICATION/JSON; charset=utf-8', 'x-request-id': 'req_0123456789abcdef',
               'authorization': SECRET, 'set-cookie': SECRET, 'x-private': SECRET}
    if scope == 'response':
        reply = httpx.Response(200, content=raw, headers=headers)
    elif scope == 'stream_event':
        headers['content-type'] = 'text/event-stream; charset=utf-8'
        reply = httpx.Response(200, text='data: ' + raw + '\n\n', headers=headers)
    else:
        reply = httpx.Response(200, json=response(calls=[call(raw)]), headers=headers)
    requests = []
    def respond(request):
        requests.append(request)
        return reply
    client_for(monkeypatch, respond)
    caplog.set_level(logging.INFO, logger='paa.latency')
    timing = Timing('json-diagnostic')
    with pytest.raises(ProviderError):
        await chat(SimpleNamespace(model_allowed_origins=()), {**CONFIG, 'streaming': scope == 'stream_event'}, SECRET, [],
                   on_timing=timing.mark)
    assert len(requests) == 1
    failures = diagnostic_entries(caplog)
    assert len(failures) == 1
    info = failures[0]
    assert info['json_scope'] == scope
    assert info['json_offset'] == info['json_input_chars'] == len(raw)
    assert info['json_line'] == (1 if scope == 'stream_event' else 2)
    assert info['json_column'] == (len(raw) + 1 if scope == 'stream_event' else 1)
    assert info['http_status'] == 200 and info['provider_request_id'] == 'req_0123456789abcdef'
    assert info['provider_request_id_header'] == 'x-request-id'
    assert info['content_type'] == ('text/event-stream' if scope == 'stream_event' else 'application/json')
    assert SECRET not in caplog.text


@pytest.mark.parametrize('header,value,expected', [
    ('x-request-id', 'req_0123456789abcdef', True),
    ('x-dashscope-request-id', '01234567-89ab-cdef-0123-456789abcdef', True),
    ('x-acs-request-id', '01234567-89AB-CDEF-0123-456789ABCDEF', True),
    ('x-request-id', '0123456789abcdef', True),
    ('x-request-id', SECRET, False),
    ('x-request-id', 'req_' + 'a' * 125, False),
    ('x-request-id', 'req_abc/def?private=' + SECRET, False),
    ('x-unknown-request-id', 'req_0123456789abcdef', False),
])
async def test_response_headers_are_explicitly_bounded_not_arbitrary_log_values(monkeypatch, caplog, header, value, expected):
    client_for(monkeypatch, lambda _: httpx.Response(200, json={}, headers={
        header: value, 'content-type': 'application/' + SECRET, 'authorization': SECRET}))
    caplog.set_level(logging.INFO, logger='paa.latency')
    with pytest.raises(ProviderError):
        await chat(SimpleNamespace(model_allowed_origins=()), CONFIG, SECRET, [], on_timing=Timing('headers').mark)
    info, = diagnostic_entries(caplog)
    assert info['content_type'] == 'other'
    assert ('provider_request_id' in info) == expected
    if expected:
        assert info['provider_request_id'] == value and info['provider_request_id_header'] == header
    assert SECRET not in caplog.text


@pytest.mark.parametrize('stage', ['framework_conversion', 'framework_tool_calls', 'completion_validation'])
async def test_post_transport_failure_is_classified_and_correlated_without_logging_exception(monkeypatch, caplog, stage):
    from app.agent.runtime.model import BoundedChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    client_for(monkeypatch, lambda _: httpx.Response(200, json=response(SECRET), headers={'x-request-id': 'req_0123456789abcdef'}))
    caplog.set_level(logging.INFO, logger='paa.latency')
    clock = Timing('post-transport', 2, 3)
    def timing(event, **fields):
        clock.mark(event, call='actual-model-call', kind='main', **fields)
    received = await chat(SimpleNamespace(model_allowed_origins=()), CONFIG, SECRET, [], on_timing=timing)
    model = BoundedChatModel(model='controlled', api_key='unused-unit-test-key')
    validations = []
    def convert(self, _response):
        if stage == 'framework_conversion':
            raise ValueError(SECRET)
        message = AIMessage(content=SECRET, invalid_tool_calls=[{'name': 'controlled', 'args': SECRET, 'error': SECRET}]
                            if stage == 'framework_tool_calls' else [])
        return ChatResult(generations=[ChatGeneration(message=message)])
    def validate(message, *, required):
        validations.append(required)
        raise ValueError(SECRET)
    monkeypatch.setattr(BoundedChatModel, '_create_chat_result', convert)
    model._completion_validator = validate
    with pytest.raises(ProviderError) as caught:
        model._checked_chat_result(received, required_completion=True, internal_kind=None, timing=timing)
    assert caught.value.code == 'invalid_response' and str(caught.value) == '模型未返回完整有效的工具参数'
    arrival, = diagnostic_entries(caplog, 'model.received')
    failure, = diagnostic_entries(caplog)
    assert arrival['provider_request_id'] == 'req_0123456789abcdef'
    assert arrival['call'] == failure['call'] == 'actual-model-call'
    assert failure['reason'] == stage and failure['body_chars'] == len(SECRET)
    assert validations == ([True] if stage == 'completion_validation' else [])
    assert SECRET not in caplog.text and SECRET not in str(caught.value)


@pytest.mark.parametrize('internal_kind,expected_calls', [(None, [False]), ('authorization', [])])
async def test_post_transport_success_and_internal_validation_behavior_are_unchanged(caplog, internal_kind, expected_calls):
    from app.agent.runtime.model import BoundedChatModel
    model = BoundedChatModel(model='controlled', api_key='unused-unit-test-key')
    validations = []
    model._completion_validator = lambda message, required: validations.append(required)
    payload = response(SECRET)
    payload['choices'][0]['message']['role'] = 'assistant'
    result = model._checked_chat_result(payload, required_completion=False, internal_kind=internal_kind, timing=Timing('success').mark)
    assert result.generations[0].message.content == SECRET and validations == expected_calls
    assert not diagnostic_entries(caplog)
