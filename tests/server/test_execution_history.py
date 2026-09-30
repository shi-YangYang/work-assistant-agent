"""Execution history preserves errors and reauthorizes bounded file references."""
import copy
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agent.tools.execution import run_python
from app.modules.deliverables.models import Deliverable, DeliverableRevision
from app.modules.executions.models import SandboxExecution
from test_builtin_execution import DATA, builtin_receipts, invoke, read
from test_business_actions import finish, runtime
from test_execution_evidence import followup

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('legacy', [False, True])
async def test_message_only_failure_is_readable_in_bounded_chunks_without_sandbox(setup, builtin_receipts, monkeypatch, legacy):
    context, sent = await runtime(setup, '读取失败原因')
    message = '控制服务失败说明。' * 700
    original = builtin_receipts.submit

    async def failed(self, body):
        result = await original(self, body)
        result.update(state='failed', error=message, stderr='', stdout='')
        return result

    monkeypatch.setattr(builtin_receipts, 'submit', failed)
    if legacy:
        first = json.loads(await run_python.coroutine(code='print(3)', title='旧执行记录', runtime=SimpleNamespace(context=context)))
    else:
        first = await invoke(context, filename='结果.csv', format='csv', data=DATA)
    assert first['state'] == 'failed' and first['message'] == message and first['stderr'] == ''
    await finish(context)
    context = await followup(setup, sent['conversationId'])
    context.settings = replace(context.settings, sandbox_url='', sandbox_token='')
    reconstructed, offset = '', 0
    while True:
        page = await read(context, first['executionId'], offset)
        assert page['state'] == 'failed' and page['stderr'] == ''
        assert page['kind'] == ('python' if legacy else 'builtin')
        assert page['deliveryState'] == 'none' and page['delivery'] == ''
        assert page['contentOffset'] == offset and page['contentTruncated']
        assert len(page['message']) <= 3000
        reconstructed += page['message']
        if page['nextOffset'] is None:
            break
        assert page['nextOffset'] > offset
        offset = page['nextOffset']
    assert reconstructed == message and builtin_receipts.count == 1


async def test_delivery_readback_uses_authorized_revision_and_reconstructable_file_references(setup, builtin_receipts, monkeypatch):
    context, sent = await runtime(setup, '导出多份表格')
    builtin_receipts.with_file = True
    original = builtin_receipts.submit

    async def files(self, body):
        result = await original(self, body)
        metadata = result['files'][0]
        result['files'] = [{**metadata, 'name': '保留完整文件名称' * 18 + str(index) + '.csv'} for index in range(12)]
        return result

    monkeypatch.setattr(builtin_receipts, 'submit', files)
    first = await invoke(context, filename='结果.csv', format='csv', data=DATA)
    assert first['state'] == 'succeeded', first
    delivery = first['delivery']
    # The persisted copy cannot supply download URLs or arbitrary delivery body.
    async with context.sessions.begin() as db:
        row = await db.get(SandboxExecution, first['executionId'])
        saved = copy.deepcopy(row.result)
        saved['delivery']['body'] = '不要回放旧成果正文'
        saved['delivery']['files'][0]['url'] = '/forged-download'
        row.result = saved
    await finish(context)
    context = await followup(setup, sent['conversationId'])
    context.settings = replace(context.settings, sandbox_url='', sandbox_token='')
    reconstructed, offset = '', 0
    while True:
        page = await read(context, first['executionId'], offset)
        assert page['deliveryState'] == 'available' and page['historical']
        assert page['contentOffset'] == offset and page['contentTruncated']
        assert len(page['delivery']) <= 3000
        reconstructed += page['delivery']
        if page['nextOffset'] is None:
            break
        assert page['nextOffset'] > offset
        offset = page['nextOffset']
    actual = json.loads(reconstructed)
    assert actual['id'] == delivery['id'] and actual['revision'] == delivery['revision']
    assert actual['files'] == delivery['files'] and len(actual['files']) == 12
    assert not {'body', 'items', 'links'} & actual.keys()
    assert '/forged-download' not in reconstructed and 'storageKey' not in reconstructed
    assert builtin_receipts.count == 1


@pytest.mark.parametrize('revoked', ['access', 'version', 'conversation', 'source'])
async def test_unavailable_delivery_hides_all_saved_references(setup, builtin_receipts, revoked):
    context, sent = await runtime(setup, '导出私有表格')
    builtin_receipts.with_file = True
    first = await invoke(context, filename='结果.csv', format='csv', data=DATA)
    assert first['state'] == 'succeeded', first
    delivery = first['delivery']
    await finish(context)
    # Keep execution permissions intact while independently invalidating its output.
    other = await followup(setup)
    async with context.sessions.begin() as db:
        item = await db.get(Deliverable, delivery['id'])
        record = await db.scalar(select(DeliverableRevision).where(
            DeliverableRevision.deliverable_id == item.id, DeliverableRevision.revision == delivery['revision']))
        if revoked == 'access':
            item.access = {'team': True, 'actorId': context.owner_id, 'companyId': context.company_id, 'reads': {}}
        elif revoked == 'version':
            await db.delete(record)
        elif revoked == 'conversation':
            from app.tasks.models import Job
            from app.modules.messages.models import Message
            job = await db.get(Job, other.job_id)
            item.conversation_id = (await db.get(Message, job.target_id)).conversation_id
        else:
            record.files = [{**file, 'sources': [{'kind': 'attachment', 'id': 'missing-source',
                                                'sha256': 'missing', 'revision': 1}]} for file in record.files]
    await finish(other)
    context = await followup(setup, sent['conversationId'])
    saved = await read(context, first['executionId'])
    assert saved['state'] == 'succeeded' and saved['executionId'] == first['executionId']
    assert saved['deliveryState'] == 'unavailable' and saved['delivery'] == ''
    serialized = json.dumps(saved, ensure_ascii=False)
    assert delivery['id'] not in serialized and delivery['files'][0]['id'] not in serialized
    assert delivery['files'][0]['url'] not in serialized and builtin_receipts.count == 1


async def test_old_receipt_without_message_or_delivery_remains_readable(setup, builtin_receipts):
    context, _ = await runtime(setup, '读取旧执行记录')
    first = json.loads(await run_python.coroutine(code='print(3)', title='旧记录', runtime=SimpleNamespace(context=context)))
    async with context.sessions.begin() as db:
        row = await db.get(SandboxExecution, first['executionId'])
        row.result = {'stdout': '3', 'stderr': '', 'exitCode': 0}
    saved = await read(context, first['executionId'])
    assert saved['kind'] == 'python' and saved['code'] == 'print(3)' and saved['stdout'] == '3'
    assert saved['message'] == '' and saved['delivery'] == '' and saved['deliveryState'] == 'none'
    assert saved['nextOffset'] is None and 'request' not in saved and builtin_receipts.count == 1
