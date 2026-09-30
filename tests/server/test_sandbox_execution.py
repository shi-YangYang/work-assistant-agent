"""Database/API semantics; real runtime isolation is tested in tests/sandbox."""
import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace
import pytest
from sqlalchemy import select, func
from app.agent.tools.execution import run_python
from app.modules.deliverables.models import DeliverableRevision
from app.modules.executions.models import SandboxExecution
from app.tasks.context import LostLease
from app.tasks.models import Job
from test_business_actions import runtime, finish
from test_deliverables import read_plan

pytestmark = pytest.mark.asyncio


class ReceiptClient:
    runs = {}
    count = 0
    data = b'a,b\n1,2\n'
    def __init__(self, settings):
        pass
    async def read(self, key):
        return self.runs.get(key)
    async def submit(self, body):
        type(self).count += 1
        key = hashlib.sha256(self.data).hexdigest()
        result = {'state': 'succeeded', 'exitCode': 0, 'stdout': '3', 'stderr': '', 'files': [
            {'id': key, 'sha256': key, 'name': '结果.csv', 'size': len(self.data), 'mimeType': 'text/csv'}]}
        self.runs[body['id']] = result
        return result
    async def file(self, key, metadata):
        return self.data
    async def best_effort(self, operation, key):
        pass


@pytest.fixture
def receipts(monkeypatch):
    ReceiptClient.runs, ReceiptClient.count = {}, 0
    monkeypatch.setattr('app.modules.executions.service.SandboxClient', ReceiptClient)
    return ReceiptClient


async def run(context, **extra):
    return json.loads(await run_python.coroutine(code='print(3)', title='计算结果', runtime=SimpleNamespace(context=context), **extra))


async def test_file_delivery_is_private_versioned_download_and_retry_is_once(setup, receipts):
    settings, sessions, users, clients = setup
    context, sent = await runtime(setup, '生成一个表格')
    first = await run(context)
    assert first['state'] == 'succeeded', first
    delivery = first['delivery']
    file = delivery['files'][0]
    assert file['url'].endswith('?revision=1')
    own = await clients['employee'].get(file['url'])
    assert own.status_code == 200 and own.content == receipts.data
    assert own.headers['cache-control'] == 'private, no-store'
    for who in ('admin', 'peer', 'outsider'):
        assert (await clients[who].get(file['url'])).status_code == 404
    replay = await run(context)
    assert replay == first and receipts.count == 1
    message = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert message['deliverables'][0]['files'] == delivery['files']
    await finish(context)
    context, _ = await runtime(setup, '修改上次文件')
    await read_plan(context, delivery['id'])
    second = await run(context, deliverable_id=delivery['id'], expected_revision=1,
                       input_refs=[{'deliverable_id': delivery['id'], 'revision': 1, 'file_id': file['id']}])
    assert second['delivery']['revision'] == 2
    assert second['delivery']['files'][0]['url'].endswith('?revision=2')
    assert (await clients['employee'].get(file['url'])).content == receipts.data
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(DeliverableRevision).where(DeliverableRevision.owner_id == users['employee'].id)) == 2
    conversation = (await clients['employee'].get('/api/v1/conversations/' + sent['conversationId'])).json()
    assert (await clients['employee'].request('DELETE', '/api/v1/conversations/' + sent['conversationId'], json={'expectedRevision': conversation['revision']})).status_code == 200
    assert (await clients['employee'].get(file['url'])).status_code == 404


async def test_sandbox_disabled_returns_honest_failure_and_does_not_publish(setup):
    context, _ = await runtime(setup, '生成一个PPT')
    context.settings = replace(context.settings, sandbox_url='', sandbox_token='')
    result = await run(context)
    assert result['state'] == 'failed' and '尚未启用' in result['message']


async def test_cross_conversation_and_foreign_inputs_are_rejected(setup, receipts):
    _, sessions, users, clients = setup
    context, _ = await runtime(setup, '生成文件')
    first = await run(context)
    await finish(context)
    peer, _ = await runtime(setup, '读取别人的文件', who='peer')
    foreign = await run(peer, input_refs=[{'deliverable_id': first['delivery']['id'], 'revision': 1, 'file_id': first['delivery']['files'][0]['id']}])
    assert foreign['state'] == 'failed' and receipts.count == 1
    assert (await run(peer, input_refs=[{'attachment_id': '../../etc/passwd'}]))['state'] == 'failed'


async def test_cancelled_lease_cannot_publish_generated_file(setup, receipts, monkeypatch):
    context, _ = await runtime(setup, '生成文件')
    original = receipts.file
    async def cancelled(self, key, metadata):
        async with context.sessions.begin() as db:
            job = await db.get(Job, context.job_id)
            job.state, job.fence = 'cancelled', job.fence + 1
        return await original(self, key, metadata)
    monkeypatch.setattr(receipts, 'file', cancelled)
    with pytest.raises(LostLease):
        await run(context)
    async with context.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(DeliverableRevision)) == 0


async def test_failed_code_is_a_receipt_and_repaired_code_uses_new_execution(setup, receipts, monkeypatch):
    context, _ = await runtime(setup, '计算')
    original = receipts.submit
    async def failed(self, body):
        if body['code'] == 'print(3)':
            type(self).count += 1
            value = {'state': 'failed', 'exitCode': 1, 'stderr': 'ValueError: bad input', 'files': []}
            self.runs[body['id']] = value
            return value
        return await original(self, body)
    monkeypatch.setattr(receipts, 'submit', failed)
    first = await run(context)
    assert first['state'] == 'failed' and 'ValueError' in first['stderr']
    assert await run(context) == first and receipts.count == 1
    fixed = json.loads(await run_python.coroutine(code='print(1+2)', title='计算结果', runtime=SimpleNamespace(context=context)))
    assert fixed['state'] == 'succeeded' and receipts.count == 2


@pytest.mark.parametrize('source_mode', ['input', 'previous-execution', 'document-read'])
async def test_removed_source_revokes_generated_file_and_deleted_account_cleanup(setup, receipts, source_mode):
    from app.modules.attachments.models import Attachment
    from app.modules.executions.cleanup import clean_files
    from app.modules.members.models import Member
    from app.db.base import uid
    settings, sessions, users, clients = setup
    context, sent = await runtime(setup, '根据附件分析')
    identifier = uid()
    data = b'input,amount\na,3\n'
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    (settings.media_dir / identifier).write_bytes(data)
    async with sessions.begin() as db:
        db.add(Attachment(id=identifier, company_id=users['employee'].company_id, owner_id=users['employee'].id,
                          message_id=sent['messageId'], kind='document', mime='text/csv', name='input.csv', size=len(data),
                          sha256=hashlib.sha256(data).hexdigest(), extraction_revision=1))
    if source_mode == 'document-read':
        context.document_versions[identifier] = 1
        result = await run(context)
    else:
        result = await run(context, input_refs=[{'attachment_id': identifier}])
        if source_mode == 'previous-execution':
            result = await run(context, step=2)
    assert result['state'] == 'succeeded'
    url = result['delivery']['files'][0]['url']
    assert (await clients['employee'].get(url)).status_code == 200
    async with sessions.begin() as db:
        item = await db.get(Attachment, identifier)
        item.deleted = True
    assert (await clients['employee'].get(url)).status_code == 403
    listing = await clients['employee'].get('/api/v1/deliverables', params={'conversationId': sent['conversationId']})
    assert listing.status_code == 200 and listing.json()['items'] == []
    restored = await clients['employee'].get('/api/v1/messages/' + sent['messageId'])
    assert restored.status_code == 200 and restored.json()['deliverables'] == []
    async with sessions.begin() as db:
        member = await db.get(Member, users['employee'].id)
        member.deleted, member.active = True, False
        await db.flush()
        await clean_files(db, settings)
    async with sessions() as db:
        rows = (await db.scalars(select(DeliverableRevision).where(DeliverableRevision.owner_id == users['employee'].id))).all()
        assert all(not row.files for row in rows)


async def test_missing_input_wrong_version_and_storage_quota_fail_without_publication(setup, receipts):
    context, _ = await runtime(setup, '生成文件')
    context.settings = replace(context.settings, generated_quota_mb=32)
    bad = await run(context, input_refs=[{'deliverable_id': 'missing', 'revision': 0, 'file_id': 'missing'}])
    assert bad['state'] == 'failed' and receipts.count == 0
    from app.modules.executions.files import file_path, validate_metadata
    with pytest.raises(Exception):
        file_path(context.settings, '../escape')
    with pytest.raises(ValueError):
        validate_metadata({'name': '../bad.pdf'})


async def test_enabled_sandbox_is_visible_to_model_without_weakening_tool_boundary(setup):
    from test_company import run_target, send
    from app.agent.prompts.policies import ALLOWED_TOOLS
    settings, sessions, users, clients = setup
    settings = replace(settings, sandbox_url='http://sandbox:8010', sandbox_token='isolated-test-not-a-real-credential')
    sent = await send(clients['employee'])
    model = await run_target(settings, sessions, users, sent)
    assert set(model.seen_tools) == ALLOWED_TOOLS
    message = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert message['job']['state'] == 'succeeded'


async def test_storage_reservation_counts_global_orphans(setup, receipts):
    context, _ = await runtime(setup, '生成文件')
    context.settings = replace(context.settings, generated_total_quota_mb=32)
    generated = context.settings.media_dir / 'generated'; generated.mkdir(parents=True, exist_ok=True)
    with (generated / 'orphan').open('wb') as file:
        file.truncate(32 * 1024 * 1024)
    result = await run(context)
    assert result['state'] == 'failed' and '存储空间已满' in result['message']
    async with context.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(DeliverableRevision)) == 0


async def test_storage_reservation_counts_existing_user_versions(setup, receipts):
    from app.modules.executions.quota import reserve
    from fastapi import HTTPException
    context, _ = await runtime(setup, '生成小文件')
    assert (await run(context))['state'] == 'succeeded'
    async with context.sessions.begin() as db:
        with pytest.raises(HTTPException) as error:
            await reserve(db, replace(context.settings, generated_quota_mb=32), setup[2]['employee'], 32 * 1024 * 1024)
        assert error.value.status_code == 422
