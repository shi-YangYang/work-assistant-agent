"""Controlled cost/ordering probes on production paths, without real model IO."""
import asyncio
import hashlib
import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.core.concurrency import map_limited
from app.integrations.models.chat import chat
from app.integrations.models.transport import task_connections
from app.modules.deliverables.models import DeliverableRevision
from app.tasks.models import Job

pytestmark = pytest.mark.asyncio


@asynccontextmanager
async def model_server():
    state = SimpleNamespace(connections=0, headers=[], writers=set())
    payload = json.dumps({'choices': [{'message': {'role': 'assistant', 'content': '完整答复'}, 'finish_reason': 'stop'}]}).encode()

    async def handle(reader, writer):
        state.connections += 1
        state.writers.add(writer)
        try:
            # A fixed per-connection cost makes the removed handshake observable.
            await asyncio.sleep(.04)
            while True:
                headers = await reader.readuntil(b'\r\n\r\n')
                state.headers.append(headers)
                size = int(next(line.split(b':', 1)[1] for line in headers.splitlines() if line.lower().startswith(b'content-length:')))
                await reader.readexactly(size)
                writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nSet-Cookie: private=unused\r\nContent-Length: ' + str(len(payload)).encode() + b'\r\n\r\n' + payload)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            state.writers.discard(writer)
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, '127.0.0.1', 0)
    state.url = 'http://127.0.0.1:' + str(server.sockets[0].getsockname()[1])
    try:
        yield state
    finally:
        server.close()
        await server.wait_closed()
        for writer in list(state.writers):
            writer.close()
        await asyncio.gather(*(writer.wait_closed() for writer in list(state.writers)))


async def test_task_connections_remove_handshakes_without_sharing_cookies_or_credentials(caplog):
    async with model_server() as server:
        settings = SimpleNamespace(model_allowed_origins=(server.url,))
        config = {'model': 'controlled', 'baseUrl': server.url, 'streaming': False}
        async def request(key):
            return await chat(settings, config, key, [{'role': 'user', 'content': '固定输入'}])
        start = time.monotonic()
        before = [await request('before') for _ in range(4)]
        sequential = time.monotonic() - start
        assert server.connections == 4
        start = time.monotonic()
        async with task_connections():
            after = [await request('after-' + str(i)) for i in range(4)]
        reused = time.monotonic() - start
        assert before == after and server.connections == 5
        assert reused < sequential
        assert all(b'Cookie:' not in headers for headers in server.headers)
        for index, headers in enumerate(server.headers[4:]):
            assert ('Bearer after-' + str(index)).encode() in headers
        async with task_connections():
            await request('new-task')
        assert server.connections == 6


async def test_task_connection_scopes_close_on_cancellation_and_do_not_share_origins(monkeypatch):
    import httpx
    import app.integrations.models.transport as transport
    instances = []
    class Probe(httpx.AsyncBaseTransport):
        def __init__(self, settings):
            self.closed = False
            instances.append(self)
        async def handle_async_request(self, request):
            return httpx.Response(200, json={'ok': True})
        async def aclose(self):
            self.closed = True
    monkeypatch.setattr(transport, 'SafeTransport', Probe)
    settings = SimpleNamespace(model_allowed_origins=())
    with pytest.raises(asyncio.CancelledError):
        async with task_connections():
            for url in ('https://first.invalid/a', 'https://first.invalid/b', 'http://first.invalid/a', 'https://second.invalid/a'):
                async with transport.client(settings) as client:
                    await client.get(url)
            assert len(instances) == 3 and not any(item.closed for item in instances)
            raise asyncio.CancelledError()
    assert all(item.closed for item in instances)


@pytest.mark.parametrize('phase', ['dns', 'connect'])
async def test_network_failure_stage_is_metadata_only_and_never_sent(monkeypatch, phase):
    import socket
    from httpcore import ConnectError
    from httpcore._backends.auto import AutoBackend
    from app.integrations.models.transport import CheckedBackend, ProviderError, request_timing
    events = []
    async def resolve(*args, **kwargs):
        if phase == 'dns':
            raise socket.gaierror('private-host-sensitive-detail')
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]
    async def connect(*args, **kwargs):
        raise ConnectError('private-host-sensitive-detail')
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', resolve)
    monkeypatch.setattr(AutoBackend, 'connect_tcp', connect)
    async with request_timing(lambda event, **fields: events.append({'event': event, **fields})):
        with pytest.raises(ProviderError) as failure:
            await CheckedBackend(SimpleNamespace(model_allowed_origins=())).connect_tcp('private-host.invalid', 443)
    assert failure.value.sent is False
    assert events[-1]['reason'] == phase and events[-1]['state'] == 'not_sent'
    assert 'private-host' not in json.dumps(events)


async def test_independent_io_is_bounded_ordered_and_cancels_siblings():
    active, maximum = 0, 0
    async def operation(value):
        nonlocal active, maximum
        active += 1
        maximum = max(active, maximum)
        try:
            await asyncio.sleep(.02 * (3 - value % 3))
            return value * 2
        finally:
            active -= 1
    assert await map_limited(range(9), operation) == [value * 2 for value in range(9)]
    assert maximum == 2 and active == 0
    started, cancelled = asyncio.Event(), asyncio.Event()
    async def fail(value):
        if value == 0:
            await started.wait()
            raise ValueError('failed input')
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    with pytest.raises(ValueError, match='failed input'):
        await map_limited([0, 1, 2], fail)
    assert cancelled.is_set()


async def test_multiple_documents_parse_concurrently_keep_order_failure_and_scope(setup, monkeypatch):
    from test_documents import upload, run
    from test_management import conversation, message
    import app.tasks.processing.documents as documents
    settings, sessions, users, clients = setup
    items = [await upload(clients['employee'], f'材料{i}.txt', f'独立材料{i}'.encode(), 'text/plain') for i in range(4)]
    sent = await message(clients['employee'], await conversation(clients['employee']), '比较材料', [item['id'] for item in items])
    active, maximum = 0, 0
    original = documents.parse_process
    parsed_order = []
    import app.core.concurrency as concurrency
    async def capture(values, operation, **kwargs):
        result = await map_limited(values, operation, **kwargs)
        parsed_order.extend(item['id'] for item in result)
        return result
    monkeypatch.setattr(concurrency, 'map_limited', capture)
    async def parse(path, suffix):
        nonlocal active, maximum
        active += 1
        maximum = max(active, maximum)
        try:
            await asyncio.sleep(.04)
            if path.name == items[1]['id']:
                return {'status': 'failed', 'chunks': [], 'info': {'error': '受控坏文件'}}
            return await original(path, suffix)
        finally:
            active -= 1
    monkeypatch.setattr(documents, 'parse_process', parse)
    # No model credentials: parses still complete before the separate model error.
    await run(settings, sessions, users, sent)
    result = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert maximum == 2 and active == 0
    assert parsed_order == [item['id'] for item in items]
    by_id = {item['id']: item for item in result['attachments']}
    assert [by_id[item['id']]['extraction']['status'] for item in items] == ['ready', 'failed', 'ready', 'ready']
    for who in ('admin', 'peer', 'outsider'):
        assert (await clients[who].get(items[0]['url'])).status_code == 404


@pytest.mark.parametrize('fail_second', [False, True])
async def test_multiple_files_download_concurrently_publish_only_complete_valid_set(setup, monkeypatch, fail_second):
    from test_sandbox_execution import ReceiptClient, run
    from test_business_actions import runtime
    active, maximum = 0, 0
    class Multiple(ReceiptClient):
        runs = {}
        async def submit(self, body):
            return {'state': 'succeeded', 'exitCode': 0, 'stdout': '', 'files': [
                {'id': hashlib.sha256(str(i).encode()).hexdigest(), 'sha256': hashlib.sha256(str(i).encode()).hexdigest(), 'name': f'{i}.txt', 'size': 1, 'mimeType': 'text/plain'} for i in range(4)]}
        async def file(self, key, metadata):
            nonlocal active, maximum
            active += 1
            maximum = max(active, maximum)
            try:
                await asyncio.sleep(.03)
                if fail_second and metadata['name'] == '1.txt':
                    raise ValueError('生成文件校验失败')
                return metadata['name'][0].encode()
            finally:
                active -= 1
    monkeypatch.setattr('app.modules.executions.service.SandboxClient', Multiple)
    context, _ = await runtime(setup, '生成四份文件')
    result = await run(context)
    assert maximum == 2 and active == 0
    if fail_second:
        assert result['state'] == 'failed'
        async with context.sessions() as db:
            assert await db.scalar(select(func.count()).select_from(DeliverableRevision)) == 0
    else:
        assert [item['name'] for item in result['delivery']['files']] == ['0.txt', '1.txt', '2.txt', '3.txt']
        for i, item in enumerate(result['delivery']['files']):
            downloaded = await setup[3]['employee'].get(item['url'])
            assert downloaded.content == str(i).encode()


async def test_structured_current_inputs_seed_definitions_without_granting_or_restoring_authority(setup):
    from dataclasses import replace
    from test_business_actions import runtime
    from app.agent.tools.catalog import loaded_groups
    context, _ = await runtime(setup, '只看看材料，不要保存')
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert loaded_groups(context, job) == []
        context.current_document_ids = ('current-document',)
        assert loaded_groups(context, job) == ['documents']
        context.work_reference_snapshot = {'id': 'current-work', 'revision': 1}
        assert loaded_groups(context, job) == ['work', 'documents']
        assert not job.result.get('toolCatalog') and not context.authorization_outcomes
        fresh = replace(context, current_document_ids=(), work_reference_snapshot=None)
        assert loaded_groups(fresh, job) == []
        fresh.work_reference_snapshot = {'id': 'revoked-work', 'unavailable': True}
        assert loaded_groups(fresh, job) == []


async def test_explicit_work_reference_saves_one_model_round_without_skipping_real_read(setup, monkeypatch):
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from pydantic import Field
    from fakes import ReviewedFixtureModel
    from test_business_actions import create
    from test_company import keyed
    from test_documents import run
    from app.agent.tools import catalog
    from app.agent.runtime import middleware
    class ReadModel(ReviewedFixtureModel):
        count: int = 0
        work: str = ''
        offered: list = Field(default_factory=list)
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            self.count += 1
            names = [tool['function']['name'] for tool in kwargs.get('tools', [])]
            self.offered.append(names)
            reads = [m for m in messages if isinstance(m, ToolMessage) and m.name == 'list_work_materials']
            if reads:
                assert json.loads(reads[-1].content)['items'] == []
                answer = AIMessage(content='这项工作目前没有材料。')
            else:
                name = 'list_work_materials' if 'list_work_materials' in names else 'load_tools'
                args = {'work_id': self.work} if name == 'list_work_materials' else {'groups': ['work']}
                answer = AIMessage(content='', tool_calls=[{'id': 'call-' + str(self.count), 'name': name, 'args': args}])
            return ChatResult(generations=[ChatGeneration(message=answer)])
    original = catalog.loaded_groups
    def without_seed(context, job):
        saved = job.result.get('toolCatalog', {})
        return [group for group in saved.get('groups', []) if group in catalog.available_groups(context)] if saved.get('scope') == catalog.scope_key(context) else []
    work = await create(setup[3]['employee'])
    counts = []
    for seeded in (False, True):
        monkeypatch.setattr(catalog, 'loaded_groups', original if seeded else without_seed)
        monkeypatch.setattr(middleware, 'loaded_groups', original if seeded else without_seed)
        sent = await setup[3]['employee'].post('/api/v1/messages', json={'text': '这项工作有哪些材料？只查看，不做修改。', 'newConversation': True, 'workReference': {'workId': work['id']}}, headers=keyed())
        assert sent.status_code == 202
        model = ReadModel(model='controlled', api_key='no-network', work=work['id'])
        await run(*setup[:3], sent.json(), model)
        result = (await setup[3]['employee'].get('/api/v1/messages/' + sent.json()['messageId'])).json()
        assert result['reply'] == '这项工作目前没有材料。', result['job']
        assert not result['actions']
        assert len([node for node in result['job']['nodes'] if node['kind'] == 'tool']) == 1
        counts.append(model.count)
    assert counts == [3, 2]


async def test_document_process_limit_is_shared_across_worker_jobs(setup, monkeypatch):
    from test_documents import upload, running_context
    from test_management import conversation, message
    from app.tasks.processing.documents import prepare_document
    settings, sessions, users, clients = setup
    contexts = []
    for who in ('employee', 'peer', 'outsider'):
        items = [await upload(clients[who], f'{i}.txt', b'bounded', 'text/plain') for i in range(2)]
        sent = await message(clients[who], await conversation(clients[who]), '读取材料', [item['id'] for item in items])
        context = await running_context(settings, sessions, users[who], sent)
        contexts.extend((context, item['id']) for item in items)
    active, maximum = 0, 0
    async def parse(*args, **kwargs):
        nonlocal active, maximum
        active += 1
        maximum = max(active, maximum)
        try:
            await asyncio.sleep(.04)
            return {'status': 'ready', 'chunks': [{'location': '行 1', 'text': 'bounded'}], 'info': {}}
        finally:
            active -= 1
    monkeypatch.setattr('app.tasks.processing.documents.parse_process', parse)
    result = await asyncio.gather(*(prepare_document(context, identifier) for context, identifier in contexts))
    assert maximum == 2 and active == 0
    assert [item['id'] for item in result] == [identifier for _, identifier in contexts]
