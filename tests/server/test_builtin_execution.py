"""Structured model tools share authorization, receipts and publication fences."""
import base64
import copy
import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.agent.runtime.middleware import ToolBoundary
from app.agent.tools.execution import read_execution, run_python
from app.agent.tools.sandbox import SANDBOX_TOOLS
from app.db.base import uid
from app.modules.attachments.models import Attachment
from app.modules.deliverables.models import DeliverableRevision
from app.modules.executions.models import SandboxExecution
from app.tasks.context import LostLease
from app.tasks.models import Job
from test_business_actions import finish, runtime
from test_company import run_target, send
from test_deliverables import read_plan
from test_execution_evidence import followup
from test_sandbox_execution import ReceiptClient

pytestmark = pytest.mark.asyncio
TOOLS = {tool.name: tool for tool in SANDBOX_TOOLS}
EXECUTION_NAMES = {'run_python', 'inspect_table', 'export_table', 'create_chart', 'create_document', 'create_slides'}
DATA = {'columns': ['编号', '数量'], 'rows': [['001', 3], ['002', 5]]}


@pytest.fixture
def builtin_receipts(monkeypatch):
    class Client(ReceiptClient):
        runs = {}
        count = 0
        bodies = []
        downloads = 0
        state = 'succeeded'
        with_file = False
        structured = {'data': {'rows': 2}, 'warnings': ['固定输入检查结果']}

        async def submit(self, body):
            type(self).bodies.append(copy.deepcopy(body))
            result = await super().submit(body)
            result.update(copy.deepcopy(self.structured), state=self.state)
            if not self.with_file:
                result['files'] = []
            if self.state != 'succeeded':
                result.update(exitCode=1, stderr='ValueError: invalid table data')
            return result

        async def file(self, key, metadata):
            type(self).downloads += 1
            return await super().file(key, metadata)

    monkeypatch.setattr('app.modules.executions.service.SandboxClient', Client)
    return Client


async def invoke(context, name='export_table', **arguments):
    return json.loads(await TOOLS[name].coroutine(runtime=SimpleNamespace(context=context), **arguments))


async def read(context, identifier='', offset=0):
    return json.loads(await read_execution.coroutine(SimpleNamespace(context=context), identifier, offset))


async def attachment(setup, sent, *, who='employee', name='输入.csv', data=b'id,value\n001,3\n002,5\n'):
    settings, sessions, users, _ = setup
    identifier = uid()
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    (settings.media_dir / identifier).write_bytes(data)
    async with sessions.begin() as db:
        db.add(Attachment(id=identifier, company_id=users[who].company_id, owner_id=users[who].id,
                          message_id=sent['messageId'], kind='document', mime='text/csv', name=name,
                          size=len(data), sha256=hashlib.sha256(data).hexdigest(), extraction_revision=1))
    return identifier


async def revision_count(context):
    async with context.sessions() as db:
        return await db.scalar(select(func.count()).select_from(DeliverableRevision).where(
            DeliverableRevision.owner_id == context.owner_id))


@pytest.mark.parametrize('name,arguments', [
    ('inspect_table', {'sample_rows': 1}),
    ('export_table', {'filename': '结果.csv', 'format': 'csv', 'data': DATA}),
    ('create_chart', {'filename': '结果.png', 'x': '编号', 'y': ['数量'], 'data': DATA}),
    ('create_document', {'filename': '结果.docx', 'title': '文档', 'blocks': [
        {'type': 'paragraph', 'text': "'); __import__('os').system('echo untrusted'); #"}]}),
    ('create_slides', {'filename': '结果.pptx', 'title': '演示文稿', 'pages': [
        {'title': '原始数据', 'blocks': [{'type': 'table', 'table': DATA}]}]}),
])
async def test_each_tool_dispatches_native_task_and_persists_original_request(setup, builtin_receipts, name, arguments):
    context, sent = await runtime(setup, '按结构化参数处理材料')
    arguments = copy.deepcopy(arguments)
    identifier = None
    if name == 'inspect_table':
        identifier = await attachment(setup, sent)
        arguments['source'] = {'input_ref': {'attachment_id': identifier}}
    result = await invoke(context, name, **arguments)
    assert result['state'] == 'succeeded', result
    assert result['kind'] == 'builtin' and result['tool'] == name
    assert result['data'] == {'rows': 2} and result['warnings'] == ['固定输入检查结果']
    body = builtin_receipts.bodies[0]
    assert set(body) == {'id', 'owner', 'task', 'inputs'}
    assert body['task']['kind'] == 'builtin' and body['task']['name'] == name and body['task']['version'] == 1
    async with context.sessions() as db:
        row = await db.get(SandboxExecution, result['executionId'])
        assert row.code == '' and row.request['name'] == name and row.request['version'] == 1
        assert row.result == result
        if identifier:
            assert row.request['arguments']['source']['input_ref']['attachment_id'] == identifier
            assert body['task']['arguments']['source']['input'] == '输入.csv'
            assert 'input_ref' not in body['task']['arguments']['source']
            assert base64.b64decode(body['inputs'][0]['data']) == b'id,value\n001,3\n002,5\n'
        else:
            assert body['task'] == row.request
        if name == 'create_document':
            assert row.request['arguments']['blocks'][0]['text'] == arguments['blocks'][0]['text']
    assert 'delivery' not in result and await revision_count(context) == 0


async def test_inspection_reuses_receipt_but_parameter_or_input_changes_execute_again(setup, builtin_receipts):
    context, sent = await runtime(setup, '检查表格')
    identifier = await attachment(setup, sent)
    source = {'input_ref': {'attachment_id': identifier}}
    first = await invoke(context, 'inspect_table', source=source)
    canonical = {'column_types': {}, 'encoding': 'utf-8-sig', 'sheet': '',
                 'input_ref': {'revision': 0, 'file_id': '', 'attachment_id': identifier, 'deliverable_id': ''}}
    assert await invoke(context, 'inspect_table', sample_rows=8, source=canonical) == first
    assert builtin_receipts.count == 1
    changed = await invoke(context, 'inspect_table', sample_rows=1, source=source)
    assert changed['state'] == 'succeeded' and changed['executionId'] != first['executionId']
    other_input = await attachment(setup, sent, data=b'id,value\n001,9\n')
    changed_input = await invoke(context, 'inspect_table', sample_rows=1,
                                 source={'input_ref': {'attachment_id': other_input}})
    assert changed_input['state'] == 'succeeded' and changed_input['executionId'] != changed['executionId']
    assert builtin_receipts.count == 3 and await revision_count(context) == 0


async def test_request_and_result_readback_are_bounded_and_reconstructable_without_sandbox(setup, builtin_receipts):
    context, sent = await runtime(setup, '生成长文档')
    paragraph = '这是原始中文内容。' * 650
    builtin_receipts.structured = {'data': {'description': '真实结果' * 1800}, 'warnings': ['保留警告']}
    first = await invoke(context, 'create_document', filename='结果.docx', title='长文档',
                         blocks=[{'type': 'paragraph', 'text': paragraph}])
    assert first['state'] == 'succeeded', first
    async with context.sessions() as db:
        snapshot = (await db.get(SandboxExecution, first['executionId'])).request
    await finish(context)
    context = await followup(setup, sent['conversationId'])
    context.settings = replace(context.settings, sandbox_url='', sandbox_token='')
    listing = await read(context)
    assert listing['items'][0]['kind'] == 'builtin' and listing['items'][0]['tool'] == 'create_document'
    fields = {'request': '', 'resultData': '', 'warnings': ''}
    offset = 0
    while True:
        page = await read(context, first['executionId'], offset)
        assert page['kind'] == 'builtin' and page['historical'] and page['code'] == ''
        assert page['contentTruncated'] and page['contentOffset'] == offset
        for field in fields:
            assert len(page[field]) <= 3000
            fields[field] += page[field]
        if page['nextOffset'] is None:
            break
        assert page['nextOffset'] > offset
        offset = page['nextOffset']
    assert json.loads(fields['request']) == snapshot
    assert json.loads(fields['resultData']) == builtin_receipts.structured['data']
    assert json.loads(fields['warnings']) == ['保留警告']
    assert builtin_receipts.count == 1


@pytest.mark.parametrize('who', ['employee', 'peer', 'outsider'])
async def test_attachment_and_execution_never_cross_conversations_or_owners(setup, builtin_receipts, who):
    context, sent = await runtime(setup, '检查私有附件')
    identifier = await attachment(setup, sent)
    first = await invoke(context, 'inspect_table', source={'input_ref': {'attachment_id': identifier}})
    assert first['state'] == 'succeeded', first
    await finish(context)
    other = await followup(setup, who=who)
    result = await invoke(other, 'inspect_table', source={'input_ref': {'attachment_id': identifier}})
    assert result['state'] == 'failed' and builtin_receipts.count == 1
    assert (await read(other))['items'] == []
    assert (await read(other, first['executionId']))['state'] == 'unavailable'


async def test_revoked_attachment_blocks_reuse_and_hides_saved_receipt(setup, builtin_receipts):
    context, sent = await runtime(setup, '检查附件')
    identifier = await attachment(setup, sent)
    source = {'input_ref': {'attachment_id': identifier}}
    first = await invoke(context, 'inspect_table', source=source)
    assert first['state'] == 'succeeded', first
    async with context.sessions.begin() as db:
        (await db.get(Attachment, identifier)).deleted = True
    assert (await invoke(context, 'inspect_table', source=source))['state'] == 'failed'
    assert (await read(context, first['executionId']))['state'] == 'unavailable'
    assert builtin_receipts.count == 1


async def test_invalid_arguments_are_rejected_before_sandbox_submission(setup, builtin_receipts):
    context, _ = await runtime(setup, '导出表格')
    invalid = [
        {'columns': ['id', 'id'], 'rows': [['001', 1]]},
        {'columns': ['id', 'value'], 'rows': [['001']]},
        {'columns': ['id'], 'rows': [['001']] * 2001},
        {'columns': ['id'], 'rows': [['x' * 2001]]},
        {'columns': ['id'], 'rows': [[float('nan')]]},
        {'columns': ['id'], 'rows': [['x' * 2000]] * 150},
    ]
    for data in invalid:
        result = await invoke(context, filename='结果.csv', format='csv', data=data)
        assert result['state'] == 'failed', result
    for source in ({'input_ref': {'attachment_id': '../etc/passwd'}},
                   {'input_ref': {'attachment_id': 'unknown', 'deliverable_id': 'mixed'}},
                   {'path': '/etc/passwd'}):
        assert (await invoke(context, 'inspect_table', source=source))['state'] == 'failed'
    assert builtin_receipts.count == 0 and await revision_count(context) == 0


@pytest.mark.parametrize('structured', [
    {'data': {'value': '界' * 23000}, 'warnings': []},
    {'data': {}, 'warnings': ['warning'] * 41},
    {'data': {}, 'warnings': ['x' * 1001]},
    {'data': {}, 'warnings': [123]},
    {'data': [], 'warnings': []},
])
async def test_oversized_or_invalid_runner_result_cannot_publish(setup, builtin_receipts, structured):
    context, _ = await runtime(setup, '导出表格')
    builtin_receipts.with_file = True
    builtin_receipts.structured = structured
    result = await invoke(context, filename='结果.csv', format='csv', data=DATA)
    assert result['state'] == 'failed' and 'delivery' not in result
    assert builtin_receipts.downloads == 0 and await revision_count(context) == 0


@pytest.mark.parametrize('state', ['failed', 'cancelled'])
async def test_failed_or_cancelled_receipt_is_reused_without_downloading_or_publishing(setup, builtin_receipts, state):
    context, _ = await runtime(setup, '导出表格')
    builtin_receipts.with_file, builtin_receipts.state = True, state
    first = await invoke(context, filename='结果.csv', format='csv', data=DATA)
    assert first['state'] == state and 'delivery' not in first
    assert await invoke(context, filename='结果.csv', format='csv', data=DATA) == first
    assert builtin_receipts.count == 1 and builtin_receipts.downloads == 0
    assert await revision_count(context) == 0


async def test_success_is_private_reused_and_revision_conflicts_do_not_overwrite(setup, builtin_receipts):
    context, sent = await runtime(setup, '导出表格')
    builtin_receipts.with_file = True
    first = await invoke(context, filename='结果.csv', format='csv', data=DATA)
    assert first['state'] == 'succeeded', first
    assert await invoke(context, filename='结果.csv', format='csv', data=DATA) == first
    assert builtin_receipts.count == 1 and await revision_count(context) == 1
    delivery = first['delivery']
    old_file = delivery['files'][0]
    for who in ('admin', 'peer', 'outsider'):
        assert (await setup[3][who].get(old_file['url'])).status_code == 404
    own = await setup[3]['employee'].get(old_file['url'])
    assert own.status_code == 200 and own.content == builtin_receipts.data
    assert own.headers['cache-control'] == 'private, no-store'
    conflict = await invoke(context, filename='结果.csv', format='csv', data={'columns': ['值'], 'rows': [[9]]})
    assert conflict['state'] == 'failed' and await revision_count(context) == 1
    await finish(context)
    context = await followup(setup, sent['conversationId'])
    await read_plan(context, delivery['id'])
    source = {'input_ref': {'deliverable_id': delivery['id'], 'revision': 1, 'file_id': old_file['id']}}
    revised = await invoke(context, filename='新版.csv', format='csv', source=source,
                           deliverable_id=delivery['id'], expected_revision=1)
    assert revised['state'] == 'succeeded' and revised['delivery']['revision'] == 2, revised
    assert revised['delivery']['id'] == delivery['id']
    body = builtin_receipts.bodies[-1]
    assert body['task']['arguments']['source']['input'] == old_file['name']
    assert base64.b64decode(body['inputs'][0]['data']) == builtin_receipts.data
    assert (await setup[3]['employee'].get(old_file['url'])).content == builtin_receipts.data
    stale = await invoke(context, filename='陈旧.csv', format='csv', data=DATA,
                         deliverable_id=delivery['id'], expected_revision=1, step=2)
    assert stale['state'] == 'failed' and await revision_count(context) == 2


async def test_lost_lease_between_download_and_commit_prevents_builtin_publication(setup, builtin_receipts, monkeypatch):
    context, _ = await runtime(setup, '导出表格')
    builtin_receipts.with_file = True
    original = builtin_receipts.file

    async def cancel(self, key, metadata):
        async with context.sessions.begin() as db:
            job = await db.get(Job, context.job_id)
            job.state, job.fence = 'cancelled', job.fence + 1
        return await original(self, key, metadata)

    monkeypatch.setattr(builtin_receipts, 'file', cancel)
    with pytest.raises(LostLease):
        await invoke(context, filename='结果.csv', format='csv', data=DATA)
    assert await revision_count(context) == 0


async def test_python_keeps_legacy_payload_identity_and_historical_readback(setup, builtin_receipts):
    context, sent = await runtime(setup, '自定义计算')
    arguments = {'code': 'print(3)', 'title': '计算结果', 'runtime': SimpleNamespace(context=context)}
    first = json.loads(await run_python.coroutine(**arguments))
    assert first['state'] == 'succeeded' and first['kind'] == 'python'
    assert json.loads(await run_python.coroutine(**arguments)) == first
    assert builtin_receipts.count == 1
    body = builtin_receipts.bodies[0]
    assert set(body) == {'id', 'owner', 'code', 'inputs'} and body['code'] == 'print(3)'
    async with context.sessions() as db:
        row = await db.get(SandboxExecution, first['executionId'])
        assert row.request is None and row.code == 'print(3)'
        # Legacy identity has no task, version or null request field.
        identity = {'job': context.job_id, 'code': 'print(3)', 'inputs': [], 'sources': [],
                    'title': '计算结果', 'target': '', 'revision': 0, 'step': 1}
        serialized = json.dumps(identity, ensure_ascii=False, sort_keys=True)
        assert row.key == hashlib.sha256(serialized.encode()).hexdigest()
    await finish(context)
    context = await followup(setup, sent['conversationId'])
    context.settings = replace(context.settings, sandbox_url='', sandbox_token='')
    saved = await read(context, first['executionId'])
    assert saved['kind'] == 'python' and saved['tool'] == 'run_python'
    assert saved['code'] == 'print(3)' and saved['stdout'] == '3' and 'request' not in saved
    assert builtin_receipts.count == 1


@pytest.mark.parametrize('enabled', [False, True])
async def test_harness_exposes_all_execution_tools_only_when_sandbox_is_configured(setup, enabled):
    settings, sessions, users, clients = setup
    settings = replace(settings, sandbox_url='http://sandbox.invalid:8010' if enabled else '',
                       sandbox_token='isolated-test-not-a-real-credential' if enabled else '')
    sent = await send(clients['employee'])
    model = await run_target(settings, sessions, users, sent)
    visible = set(model.seen_tools)
    assert EXECUTION_NAMES <= visible if enabled else not EXECUTION_NAMES & visible
    assert 'read_execution' in visible
    result = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert result['job']['state'] == 'succeeded', result


async def test_disabled_sandbox_rejects_all_execution_calls_at_boundary(setup):
    context, _ = await runtime(setup, '普通问答')
    context.settings = replace(context.settings, sandbox_url='', sandbox_token='')
    called = []

    async def handler(request):
        called.append(request.tool_call['name'])

    for name in EXECUTION_NAMES:
        request = SimpleNamespace(runtime=SimpleNamespace(context=context),
                                  tool_call={'name': name, 'id': uid(), 'args': {}}, state={'messages': []})
        with pytest.raises(RuntimeError, match='Tool is not allowed'):
            await ToolBoundary().awrap_tool_call(request, handler)
    assert called == []
    assert (await invoke(context, filename='结果.csv', format='csv', data=DATA))['state'] == 'failed'
    assert await revision_count(context) == 0
