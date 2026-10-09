"""Real HTTP endings, bounded post-DONE cleanup and cancellation."""
import asyncio
import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.integrations.models import transport
from app.integrations.models.chat import chat

pytestmark = pytest.mark.asyncio


@asynccontextmanager
async def stream_server(mode='complete'):
    state = SimpleNamespace(connections=0, requests=0, closed=0, writers=set())
    data = ('data: ' + json.dumps({'choices': [{'delta': {'content': 'answer'}, 'finish_reason': 'stop'}]}) + '\n\ndata: [DONE]\n\n').encode()

    async def serve(reader, writer):
        state.connections += 1
        state.writers.add(writer)
        try:
            while True:
                headers = await reader.readuntil(b'\r\n\r\n')
                size = int(next(line.split(b':', 1)[1] for line in headers.splitlines() if line.lower().startswith(b'content-length:')))
                await reader.readexactly(size)
                state.requests += 1
                writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\n\r\n' + f'{len(data):x}\r\n'.encode() + data + b'\r\n')
                if mode == 'complete':
                    writer.write(b'0\r\n\r\n')
                elif mode == 'oversized':
                    tail = b': ' + b'x' * 9000 + b'\n'
                    writer.write(f'{len(tail):x}\r\n'.encode() + tail + b'\r\n')
                elif mode == 'many_lines':
                    tail = b'\n' * 256
                    writer.write(f'{len(tail):x}\r\n'.encode() + tail + b'\r\n')
                elif mode == 'malformed':
                    writer.write(b'not-a-chunk\r\n')
                elif mode == 'reset':
                    writer.close()
                    break
                await writer.drain()
                if mode != 'complete':
                    assert await reader.read(1) == b''
                    break
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            state.closed += 1
            state.writers.discard(writer)
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(serve, '127.0.0.1', 0)
    state.url = 'http://127.0.0.1:' + str(server.sockets[0].getsockname()[1])
    try:
        yield state
    finally:
        server.close()
        await server.wait_closed()
        for writer in list(state.writers):
            writer.close()
        await asyncio.gather(*(writer.wait_closed() for writer in list(state.writers)), return_exceptions=True)


async def request(server):
    return await chat(SimpleNamespace(model_allowed_origins=(server.url,)),
                      {'model': 'controlled', 'baseUrl': server.url, 'streaming': True},
                      'no-secret', [{'role': 'user', 'content': 'probe'}])


async def test_complete_chunked_stream_reuses_connection_with_tcp_kept_open():
    async with stream_server() as server:
        async with transport.task_connections():
            for _ in range(4):
                result = await request(server)
                assert result['choices'][0]['message']['content'] == 'answer'
            assert server.connections == 1 and server.requests == 4
        async with transport.task_connections():
            await request(server)
        assert server.connections == 2


@pytest.mark.parametrize('mode', ['stalled', 'oversized', 'many_lines', 'malformed', 'reset'])
async def test_post_done_tail_is_bounded_discarded_and_never_reused(mode):
    async with stream_server(mode) as server:
        started = time.monotonic()
        async with transport.task_connections():
            for _ in range(2):
                result = await request(server)
                assert result['choices'][0]['message']['content'] == 'answer'
        assert server.connections == 2
        assert time.monotonic() - started < 1
        await asyncio.sleep(0)
        assert server.closed == 2


async def test_external_cancel_during_tail_propagates_and_closes(monkeypatch):
    entered = asyncio.Event()
    finish = transport.finish_stream
    async def notify(lines):
        entered.set()
        await finish(lines)
    monkeypatch.setattr(transport, 'finish_stream', notify)
    async with stream_server('stalled') as server:
        async def invoke():
            async with transport.task_connections():
                return await request(server)
        task = asyncio.create_task(invoke())
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)
        assert server.closed == 1
