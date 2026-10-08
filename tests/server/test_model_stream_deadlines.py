"""Slow useful generation may continue; idle streams and total budgets stay bounded."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from app.agent.runtime.model import request_with_deadline, response_timeout
from app.integrations.models.chat import chat
from app.integrations.models.transport import LimitedStream, ProviderError, SafeTransport


@pytest.mark.parametrize(('retry', 'streaming', 'remaining', 'expected'), [
    (True, True, 420, 420), (True, False, 420, 60),
    (False, True, 420, 60), (False, False, 420, 60),
    (True, True, 10, 10), (True, False, 10, 10),
])
def test_runtime_keeps_existing_total_and_nonstream_limits(monkeypatch, retry, streaming, remaining, expected):
    monkeypatch.setattr('app.agent.runtime.model.time.time', lambda: 1000)
    context = SimpleNamespace(node_retry=retry, node_deadline=1000 + remaining)
    assert response_timeout(context, streaming) == expected


@pytest.mark.asyncio
async def test_progress_renews_idle_past_sixty_without_moving_total_deadline(monkeypatch):
    clock, scheduled = [1000], []
    class Guard:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def reschedule(self, deadline):
            scheduled.append(deadline)
    def timer(deadline):
        scheduled.append(deadline)
        return Guard()
    monkeypatch.setattr('app.agent.runtime.model.asyncio.get_running_loop', lambda: SimpleNamespace(time=lambda: clock[0]))
    monkeypatch.setattr('app.agent.runtime.model.asyncio.timeout_at', timer)
    async def request(progress):
        for elapsed in (30, 59, 70, 390, 419):
            clock[0] = 1000 + elapsed
            progress()
        return 'complete'
    assert await request_with_deadline(request, timeout=420, idle_timeout=60) == 'complete'
    assert scheduled == [1060, 1090, 1119, 1130, 1420, 1420]


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['idle', 'heartbeat', 'total'])
async def test_stalled_and_total_deadlines_cancel_inflight_request(mode):
    closed = []
    async def request(progress):
        try:
            while True:
                await asyncio.sleep(.002)
                if mode == 'total':
                    progress()
                # Empty wire heartbeats do not call the useful-progress callback.
        finally:
            closed.append(True)
    with pytest.raises(TimeoutError):
        await request_with_deadline(request, timeout=.04, idle_timeout=.01)
    assert closed == [True]


@pytest.mark.asyncio
async def test_external_cancel_is_preserved_and_closes_request():
    entered, closed = asyncio.Event(), []
    async def request(progress):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            closed.append(True)
    task = asyncio.create_task(request_with_deadline(request, timeout=420, idle_timeout=60))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed == [True]


@pytest.mark.asyncio
async def test_parser_counts_only_useful_progress_without_exporting_reasoning(monkeypatch):
    hidden = 'private reasoning must never reach output or event persistence'
    deltas = [
        {'role': 'assistant', 'content': '', 'reasoning_content': ''}, {},
        {'content': ' ', 'reasoning_content': ' '},
        {'reasoning_content': hidden}, {'content': 'answer'},
        {'tool_calls': [{'index': 0, 'id': 'call', 'function': {'name': 'finish_task'}}]},
        {'tool_calls': [{'index': 0, 'function': {'arguments': '{}'}}]},
    ]
    events = [{'choices': [{'delta': delta}]} for delta in deltas]
    events.append({'choices': [{'delta': {}, 'finish_reason': 'tool_calls'}]})
    payload = ': heartbeat\n\n' + ''.join('data: ' + json.dumps(value) + '\n\n' for value in events) + 'data: [DONE]\n\n'
    def response(request):
        assert request.extensions['paa_model_stream_timeout'] == 180
        return httpx.Response(200, text=payload)
    monkeypatch.setattr('app.integrations.models.transport.client', lambda settings: httpx.AsyncClient(transport=httpx.MockTransport(response)))
    progress, records, fragments = [], [], []
    async def event(*values):
        records.append(values)
    async def delta(value):
        fragments.append(value)
    result = await chat(SimpleNamespace(model_allowed_origins=()),
        {'baseUrl': 'https://example.com/v1', 'model': 'controlled', 'streaming': True}, 'test',
        [{'role': 'user', 'content': 'request'}], stream_timeout=180,
        on_progress=lambda: progress.append(True), on_event=event, on_delta=delta)
    assert progress == [True, True, True]
    assert hidden not in str((result, records, fragments))
    assert result['choices'][0]['message']['content'] == ' answer'


@pytest.mark.asyncio
async def test_nonstream_does_not_opt_into_long_stream_budget(monkeypatch):
    def response(request):
        assert 'paa_model_stream_timeout' not in request.extensions
        return httpx.Response(200, json={'choices': [{'message': {'content': 'answer'}, 'finish_reason': 'stop'}]})
    monkeypatch.setattr('app.integrations.models.transport.client', lambda settings: httpx.AsyncClient(transport=httpx.MockTransport(response)))
    progress = []
    await chat(SimpleNamespace(model_allowed_origins=()),
        {'baseUrl': 'https://example.com/v1', 'model': 'controlled', 'streaming': False}, 'test',
        [{'role': 'user', 'content': 'request'}], stream_timeout=180, on_progress=lambda: progress.append(True))
    assert progress == []


class Bytes(httpx.AsyncByteStream):
    def __init__(self, value):
        self.value = value
    async def __aiter__(self):
        yield self.value


@pytest.mark.asyncio
@pytest.mark.parametrize('explicit', [False, True])
async def test_transport_duration_override_is_explicit_and_retains_size_bound(monkeypatch, explicit):
    async def response(self, request):
        return httpx.Response(200, stream=Bytes(b'chunk'))
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', response)
    transport = SafeTransport(SimpleNamespace(model_allowed_origins=()))
    extension = {'paa_model_stream_timeout': 180} if explicit else {}
    response = await transport.handle_async_request(httpx.Request('POST', 'https://example.com', extensions=extension))
    clock = iter([0, 66])
    monkeypatch.setattr('app.integrations.models.transport.time.monotonic', lambda: next(clock))
    try:
        if explicit:
            assert b''.join([part async for part in response.stream]) == b'chunk'
        else:
            with pytest.raises(ProviderError, match='时间限制'):
                _ = [part async for part in response.stream]
        clock = iter([0, 1])
        with pytest.raises(ProviderError, match='大小或时间限制'):
            _ = [part async for part in LimitedStream(Bytes(b'x' * (2 * 1024 * 1024 + 1)), 180 if explicit else 65)]
    finally:
        monkeypatch.undo()
        await transport.aclose()
