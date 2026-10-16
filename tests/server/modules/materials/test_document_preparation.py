"""Preparation scheduling/cancellation faults use owned tasks and a test database."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from _support.agent.fakes import controlled_model
from _support.http.management import conversation, message
from _support.materials.documents import run, running_context, upload
from _support.materials.legacy_samples import TEXT, legacy_samples
from app.db.base import now
from app.integrations.parsing.office_conversion import converter
from app.modules.attachments.models import Attachment, DocumentChunk
from app.tasks.context import LostLease
from app.tasks.models import Job
from app.tasks.processing import documents
from app.tasks.runtime.queue import claim

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope='module')
def real_doc():
    if not converter()[0]:
        pytest.skip('Real LibreOffice is required for preparation recovery tests')
    return legacy_samples()['sample.doc']


async def test_shared_conversion_survives_one_cancel_and_releases_when_everyone_cancels():
    entered, release, ended = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls, cache = [], {}
    async def operation():
        calls.append(True)
        entered.set()
        try:
            await release.wait()
            return {'status': 'ready', 'chunks': [], 'info': {}}
        finally:
            ended.set()
    first = asyncio.create_task(documents.shared_parse(cache, 'owned-input', operation))
    await asyncio.wait_for(entered.wait(), 5)
    second = asyncio.create_task(documents.shared_parse(cache, 'owned-input', operation))
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert not ended.is_set() and not second.done()
    release.set()
    assert (await second)['status'] == 'ready'
    assert len(calls) == 1 and ended.is_set()
    entered.clear(); release.clear(); ended.clear()
    owners = [asyncio.create_task(documents.shared_parse(cache, 'new-input', operation)) for _ in range(2)]
    await asyncio.wait_for(entered.wait(), 5)
    for owner in owners:
        owner.cancel()
    results = await asyncio.gather(*owners, return_exceptions=True)
    assert all(isinstance(result, asyncio.CancelledError) for result in results)
    assert ended.is_set() and cache['new-input'].task.done() and cache['new-input'].users == 0


async def test_slow_conversion_queue_does_not_block_modern_files_or_another_account(setup, monkeypatch):
    settings, sessions, users, clients = setup
    first_started, second_waiting, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    heavy_slot = asyncio.Semaphore(1)
    converts = []
    async def slow(path, suffix, *, on_stage):
        converts.append(str(path))
        if len(converts) == 2:
            second_waiting.set()
        async with heavy_slot:
            await on_stage('converting')
            first_started.set()
            await release.wait()
            return {'status': 'ready', 'chunks': [{'text': 'controlled slow conversion', 'location': '段落 1'}], 'info': {}}
    monkeypatch.setattr(documents, 'parse_office', slow)
    client = clients['employee']
    files = [await upload(client, f'排队-{index}.doc', b'{\\rtf1 owned queue ' + str(index).encode() + b'}') for index in range(2)]
    fast = await upload(client, '立即读取.txt', b'FAST_FILE_REAL_PARSE')
    sent = await message(client, await conversation(client), '处理混合资料', [f['id'] for f in [*files, fast]])
    task = asyncio.create_task(run(settings, sessions, users, sent, controlled_model('clarify')))
    try:
        await asyncio.wait_for(first_started.wait(), 5)
        await asyncio.wait_for(second_waiting.wait(), 5)
        async def ready():
            while True:
                async with sessions() as db:
                    row = await db.get(Attachment, fast['id'])
                    if row.extraction_status == 'ready':
                        assert await db.scalar(select(DocumentChunk.text).where(DocumentChunk.attachment_id == row.id)) == 'FAST_FILE_REAL_PARSE'
                        return
                await asyncio.sleep(0.02)
        await asyncio.wait_for(ready(), 5)
        assert not task.done()
        peer = await message(clients['peer'], await conversation(clients['peer']), '另一用户普通问题')
        await asyncio.wait_for(run(settings, sessions, users, peer, controlled_model('clarify')), 10)
        data = (await clients['peer'].get('/api/v1/messages/' + peer['messageId'])).json()
        assert data['job']['state'] == 'awaiting_input' and data['reply']
    finally:
        release.set()
        await task
    data = (await client.get('/api/v1/messages/' + sent['messageId'])).json()
    assert [f['id'] for f in data['attachments']] == [f['id'] for f in [*files, fast]]
    assert all(f['extraction']['status'] == 'ready' for f in data['attachments'])


async def test_cancelled_shared_attachment_does_not_cancel_other_attachment_and_retry_is_clean(setup, real_doc, monkeypatch):
    settings, sessions, users, clients = setup
    client = clients['employee']
    files = [await upload(client, '同一原件.doc', real_doc) for _ in range(2)]
    sent = await message(client, await conversation(client), '读取两个附件', [f['id'] for f in files])
    context = await running_context(settings, sessions, users['employee'], sent)
    entered, release, calls, cache = asyncio.Event(), asyncio.Event(), [], {}
    convert = documents.parse_office
    async def gated(*args, **kwargs):
        calls.append(True); entered.set()
        await release.wait()
        return await convert(*args, **kwargs)
    monkeypatch.setattr(documents, 'parse_office', gated)
    first = asyncio.create_task(documents.prepare_document(context, files[0]['id'], parse_cache=cache))
    await asyncio.wait_for(entered.wait(), 5)
    second = asyncio.create_task(documents.prepare_document(context, files[1]['id'], parse_cache=cache))
    async def attached():
        while not any(entry.users == 2 for entry in cache.values()):
            await asyncio.sleep(0.01)
    await asyncio.wait_for(attached(), 5)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    result = await second
    assert result['extraction']['status'] == 'ready' and len(calls) == 1
    retry = await documents.prepare_document(context, files[0]['id'], parse_cache=cache)
    assert retry['extraction']['status'] == 'ready' and retry['extraction']['revision'] == 2
    assert len(calls) == 1
    async with sessions() as db:
        for item, revision in ((files[0], 2), (files[1], 1)):
            chunks = (await db.scalars(select(DocumentChunk).where(DocumentChunk.attachment_id == item['id']))).all()
            assert chunks and {c.revision for c in chunks} == {revision}
            assert TEXT in '\n'.join(c.text for c in chunks)


async def test_database_failure_before_persistence_recovers_on_new_lease_without_late_write(setup, real_doc, monkeypatch):
    settings, sessions, users, clients = setup
    item = await upload(clients['employee'], '恢复原件.doc', real_doc)
    sent = await message(clients['employee'], await conversation(clients['employee']), '读取合同', [item['id']])
    context = await running_context(settings, sessions, users['employee'], sent)
    convert = documents.parse_office
    parsed = asyncio.Event()
    async def marked(*args, **kwargs):
        result = await convert(*args, **kwargs)
        assert result['status'] == 'ready', result
        parsed.set()
        return result
    monkeypatch.setattr(documents, 'parse_office', marked)
    class FailFinalTransaction:
        @asynccontextmanager
        async def begin(self):
            if parsed.is_set():
                raise OperationalError('owned commit failure', {}, OSError('controlled database unavailable'))
            async with sessions.begin() as db:
                yield db
    broken = replace(context, sessions=FailFinalTransaction())
    with pytest.raises(OperationalError):
        await documents.prepare_document(broken, item['id'])
    async with sessions.begin() as db:
        row = await db.get(Attachment, item['id'])
        assert row.extraction_status == 'processing'
        assert not await db.scalar(select(DocumentChunk.id).where(DocumentChunk.attachment_id == item['id']))
        job = await db.get(Job, sent['jobId'])
        job.lease_until = now() - timedelta(seconds=1)
    # Real queue recovery increments the fence; the prior execution cannot commit.
    recovered = await claim(sessions, users['employee'].id)
    assert recovered.id == sent['jobId'] and recovered.fence > context.fence
    with pytest.raises(LostLease):
        await documents.prepare_document(context, item['id'])
    current = replace(context, fence=recovered.fence)
    result = await documents.prepare_document(current, item['id'])
    assert result['extraction']['status'] == 'ready' and result['extraction']['revision'] == 2
    async with sessions() as db:
        chunks = (await db.scalars(select(DocumentChunk).where(DocumentChunk.attachment_id == item['id']))).all()
        assert chunks and all(c.revision == 2 for c in chunks)
        assert TEXT in '\n'.join(c.text for c in chunks)
    # Both the source bytes and another account's subsequent job remain usable.
    assert (await clients['employee'].get(item['url'])).content == real_doc
    peer = await message(clients['peer'], await conversation(clients['peer']), '恢复后普通问题')
    await run(settings, sessions, users, peer, controlled_model('clarify'))
    assert (await clients['peer'].get('/api/v1/messages/' + peer['messageId'])).json()['reply']


@pytest.mark.parametrize('stop_at', ['queued', 'converting', 'before_persist'])
async def test_api_cancel_conversion_at_each_boundary_then_retry(setup, real_doc, monkeypatch, stop_at):
    settings, sessions, users, clients = setup
    client = clients['employee']
    entered, released, cleaned = asyncio.Event(), asyncio.Event(), asyncio.Event()
    convert = documents.parse_office
    async def paused(path, suffix, *, on_stage):
        async def stage(value):
            await on_stage(value)
            if value == stop_at:
                entered.set()
                await released.wait()
        try:
            result = await convert(path, suffix, on_stage=stage)
            if stop_at == 'before_persist':
                assert result['status'] == 'ready', result
                entered.set()
                await released.wait()
            return result
        finally:
            cleaned.set()
    monkeypatch.setattr(documents, 'parse_office', paused)
    monkeypatch.setattr('app.tasks.runtime.cancellation.CANCEL_POLL_SECONDS', 0.02)
    files = [await upload(client, '取消原件.doc', real_doc) for _ in range(2)]
    sent = await message(client, await conversation(client), '读取原件', [f['id'] for f in files])
    task = asyncio.create_task(run(settings, sessions, users, sent, controlled_model('clarify')))
    try:
        await asyncio.wait_for(entered.wait(), 20)
        job = (await client.get('/api/v1/jobs/' + sent['jobId'])).json()
        cancelled = await client.post('/api/v1/jobs/' + sent['jobId'] + '/cancel', json={'expectedAttempt': job['attempt'], 'expectedFence': job['fence']})
        assert cancelled.status_code == 200, cancelled.text
        await asyncio.wait_for(task, 10)
        assert cleaned.is_set()
        released.set()
        data = (await client.get('/api/v1/messages/' + sent['messageId'])).json()
        assert data['job']['state'] == 'cancelled' and not data['reply']
        assert all(f['extraction']['status'] == 'failed' for f in data['attachments'])
        async with sessions() as db:
            assert not await db.scalar(select(DocumentChunk.id).where(DocumentChunk.attachment_id.in_([f['id'] for f in files])))
    finally:
        released.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    monkeypatch.setattr(documents, 'parse_office', convert)
    # The public document retry must remain usable after the message was cancelled.
    retry = await client.post('/api/v1/uploads/' + files[0]['id'] + '/retry', json={})
    assert retry.status_code == 202, retry.text
    await run(settings, sessions, users, {'jobId': retry.json()['id']})
    detail = (await client.get('/api/v1/uploads/' + files[0]['id'] + '/extraction')).json()
    assert detail['attachment']['extraction']['status'] == 'ready'
    assert detail['attachment']['extraction']['revision'] == 2
    assert TEXT in '\n'.join(row['text'] for row in detail['items'])
    login = await clients['peer'].post('/api/v1/auth/login', json={'username': users['peer'].username, 'password': 'controlled-test-password'})
    assert login.status_code == 200, login.text
    clients['peer'].headers['X-CSRF-Token'] = login.json()['csrf']
    ordinary = await message(clients['peer'], await conversation(clients['peer']), '取消后仍可正常问答')
    await run(settings, sessions, users, ordinary, controlled_model('clarify'))
    data = (await clients['peer'].get('/api/v1/messages/' + ordinary['messageId'])).json()
    assert data['job']['state'] == 'awaiting_input' and data['reply'] and not data['job']['error']
