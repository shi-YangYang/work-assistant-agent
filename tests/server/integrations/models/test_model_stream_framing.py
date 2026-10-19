"""Controlled wire fixtures for SSE framing, not real model quality evaluation."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from app.integrations.models.chat import chat
from app.integrations.models.transport import ProviderError
from app.tasks.nodes.node_failures import classify
from _support.agent.model_stream_errors import client_for


pytestmark = pytest.mark.asyncio
CONFIG = {'baseUrl': 'https://example.com/v1', 'model': 'controlled', 'streaming': True, 'parameters': {}}
SECRET = 'private-content-never-log'


def event(value, newline='\n'):
    return newline.join('data: ' + line for line in json.dumps(value, indent=1).splitlines()) + newline * 2


async def request(**kwargs):
    return await chat(SimpleNamespace(model_allowed_origins=()), CONFIG, 'unused-test-key', [], **kwargs)


class ChunkedWire(httpx.AsyncByteStream):
    def __init__(self, wire):
        self.wire = wire.encode('utf-8')

    async def __aiter__(self):
        # Include split CRLF pairs, BOM bytes and non-ASCII characters.
        for index in range(0, len(self.wire), 2):
            yield self.wire[index:index + 2]


@pytest.mark.parametrize('newline', ['\n', '\r\n', '\r'])
@pytest.mark.parametrize('bom', ['', '\ufeff'])
async def test_multiline_events_preserve_response_and_incremental_callbacks(monkeypatch, newline, bom):
    content = '中文 ' + SECRET
    wire = bom + newline * 2 + ': heartbeat' + newline * 2 + 'event: message' + newline + 'id: ignored' + newline
    wire += event({'choices': [{'delta': {'content': content}, 'finish_reason': 'stop'}]}, newline)
    wire += 'data: [DONE]' + newline * 2
    calls, deltas = [], []
    def response(incoming):
        calls.append(incoming)
        return httpx.Response(200, stream=ChunkedWire(wire), headers={'content-type': 'text/event-stream'})
    async def receive(delta):
        deltas.append(delta.text)
    client_for(monkeypatch, response)
    result = await request(on_delta=receive)
    assert result['choices'][0]['message']['content'] == content
    assert deltas == [content] and len(calls) == 1


async def test_multiline_tool_events_preserve_separate_argument_fragments(monkeypatch):
    wire = event({'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'call-1', 'function': {'name': 'test_tool', 'arguments': '{"a":'}}]}}]})
    wire += event({'choices': [{'delta': {'tool_calls': [{'index': 0, 'function': {'arguments': '1}'}}]}, 'finish_reason': 'tool_calls'}]})
    wire += 'data: [DONE]\n\n'
    client_for(monkeypatch, lambda _: httpx.Response(200, text=wire))
    result = await request()
    call, = result['choices'][0]['message']['tool_calls']
    assert call == {'id': 'call-1', 'type': 'function', 'function': {'name': 'test_tool', 'arguments': '{"a":1}'}}


async def test_multiline_error_keeps_safe_classification_and_retry_policy(monkeypatch, caplog):
    wire = 'event: error\n' + event({'error': {'code': 'insufficient_quota', 'message': SECRET}})
    client_for(monkeypatch, lambda _: httpx.Response(200, text=wire))
    with pytest.raises(ProviderError) as caught:
        await request()
    assert caught.value.code == 'quota' and not classify(caught.value).retryable
    assert SECRET not in str(caught.value) and SECRET not in caplog.text


@pytest.mark.parametrize('ending', ['missing_done', 'unfinished_done', 'unfinished_event'])
async def test_eof_never_completes_an_unterminated_event_or_answer(monkeypatch, ending):
    wire = event({'choices': [{'delta': {'content': 'partial'}, 'finish_reason': 'stop'}]})
    if ending == 'unfinished_done':
        wire += 'data: [DONE]\n'
    elif ending == 'unfinished_event':
        wire = wire[:-1]
    client_for(monkeypatch, lambda _: httpx.Response(200, text=wire))
    with pytest.raises(ProviderError) as caught:
        await request()
    assert caught.value.code == 'interrupted'


async def test_complete_event_with_invalid_json_still_fails_safely(monkeypatch, caplog):
    wire = 'data: {\ndata: "secret": "' + SECRET + '",\n\n'
    client_for(monkeypatch, lambda _: httpx.Response(200, text=wire))
    with pytest.raises(ProviderError) as caught:
        await request()
    assert caught.value.code == 'invalid_response'
    assert SECRET not in str(caught.value) and SECRET not in caplog.text


async def test_multiline_event_cannot_bypass_existing_response_memory_bound(monkeypatch):
    monkeypatch.setattr('app.integrations.models.transport.MAX_RESPONSE_BYTES', 64)
    wire = 'data: ' + 'a' * 32 + '\n' + 'data: ' + 'b' * 32 + '\n\n'
    client_for(monkeypatch, lambda _: httpx.Response(200, text=wire))
    with pytest.raises(ProviderError) as caught:
        await request()
    assert caught.value.code == 'limit' and not classify(caught.value).retryable


async def test_completed_event_is_published_before_next_network_chunk(monkeypatch):
    received = asyncio.Event()
    class Wire(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield event({'choices': [{'delta': {'content': 'first'}}]}).encode()
            await asyncio.wait_for(received.wait(), timeout=1)
            yield (event({'choices': [{'delta': {}, 'finish_reason': 'stop'}]}) + 'data: [DONE]\n\n').encode()
    client_for(monkeypatch, lambda _: httpx.Response(200, stream=Wire()))
    async def receive(delta):
        assert delta.text == 'first'
        received.set()
    result = await request(on_delta=receive)
    assert result['choices'][0]['message']['content'] == 'first'


async def test_comments_do_not_count_as_progress_and_cancellation_is_not_retried(monkeypatch):
    calls, progress = [], []
    class Wire(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b': heartbeat\n\nevent: keepalive\n\n\n'
            raise asyncio.CancelledError()
    def response(incoming):
        calls.append(incoming)
        return httpx.Response(200, stream=Wire())
    client_for(monkeypatch, response)
    with pytest.raises(asyncio.CancelledError):
        await request(on_progress=lambda: progress.append(True))
    assert len(calls) == 1 and not progress
