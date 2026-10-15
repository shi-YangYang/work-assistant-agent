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
