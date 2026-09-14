import asyncio
from datetime import timedelta
import io
import json
from types import SimpleNamespace
from uuid import uuid4
import pytest
from PIL import Image
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import func, select, text
from paa_server.agent.harness import RunContext, find_documents, read_document, propose_progress, lease, InputChanged, LostLease
from paa_server.documents import DOCUMENT_TYPES, agent_attachment, prepare_document, verified_citations
from paa_server.models import Attachment, DocumentChunk, Job, Message, ModelUsage, ProgressDraft, Report, ReportRevision, WorkItem, WorkRevision, now
from paa_server.worker import process_job
from document_samples import samples
from document_fakes import document_model
from test_management import conversation, message, remove
from test_company import keyed

pytestmark = pytest.mark.asyncio


async def upload(client, name='演示项目.txt', data=None, mime=None):
    response = await client.post('/api/v1/uploads', files={'file': (name, samples()[name] if data is None else data, mime or DOCUMENT_TYPES.get('.' + name.split('.')[-1], 'application/octet-stream'))})
    assert response.status_code == 201, response.text
    return response.json()


async def run(settings, sessions, users, sent, model=None):
    async with sessions.begin() as db:
        job = await db.get(Job, sent['jobId'])
        job.state, job.fence, job.lease_until = 'running', job.fence + 1, now() + timedelta(seconds=90)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(job, sessions, settings, saver, model=model)
    return job


async def running_context(settings, sessions, actor, sent):
    async with sessions.begin() as db:
        job = await db.get(Job, sent['jobId'])
        job.state, job.fence, job.lease_until = 'running', job.fence + 1, now() + timedelta(seconds=90)
    return RunContext(actor.id, actor.company_id, job.id, job.fence, sessions, settings)


async def test_upload_parsing_without_key_per_file_failure_and_model_retry_reuse(setup, monkeypatch):
    settings, sessions, users, c = setup
    conv = await conversation(c['employee'])
    good = await upload(c['employee'])
    bad = await upload(c['employee'], 'bad.json', b'{invalid', 'application/json')
    assert good['extraction']['status'] == 'unsent'
    for client in (c['admin'], c['peer'], c['outsider']):
        assert (await client.get(good['url'])).status_code == 404
        assert (await client.get('/api/v1/uploads/' + good['id'] + '/extraction')).status_code == 404
    sent = await message(c['employee'], conv, '', [good['id'], bad['id']])
    await run(settings, sessions, users, sent)
    data = (await c['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    states = {a['id']: a['extraction'] for a in data['attachments']}
    assert states[good['id']]['status'] == 'ready'
    assert states[bad['id']]['status'] == 'failed' and 'JSON' in states[bad['id']]['error']
    assert data['job']['state'] == 'failed' and '模型' in data['job']['error']
    for client, expected in ((c['admin'], 200), (c['peer'], 404), (c['outsider'], 404)):
        assert (await client.get(good['url'])).status_code == expected
        assert (await client.get('/api/v1/uploads/' + good['id'] + '/extraction')).status_code == expected
    assert (await c['employee'].get(good['url'])).content == samples()['演示项目.txt']
    revision = states[good['id']]['revision']
    assert (await c['employee'].post('/api/v1/jobs/' + sent['jobId'] + '/retry', json={})).status_code == 200
    model = document_model('后半部分标记')
    await run(settings, sessions, users, sent, model)
    data = (await c['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert data['job']['state'] == 'awaiting_input', data
    assert '后半部分标记' in data['reply'] and data['citations'][0]['ordinal'] >= 3
    assert not data['drafts'] and not (await c['employee'].get('/api/v1/work-items')).json()['items']
    assert next(a for a in data['attachments'] if a['id'] == good['id'])['extraction']['revision'] == revision
    assert model.seen[0]['items'][0]['location'].startswith('行 91')
    # The dedicated retry only parses and does not reserve a model call.
    before = data['reply']
    retried = await c['employee'].post('/api/v1/uploads/' + bad['id'] + '/retry', json={})
    assert retried.status_code == 202, retried.text
    await run(settings, sessions, users, {'jobId': retried.json()['id']})
    assert (await c['employee'].get('/api/v1/messages/' + sent['messageId'])).json()['reply'] == before
    async with sessions() as db:
        assert not await db.scalar(select(func.count()).select_from(ModelUsage).where(ModelUsage.company_id == users['employee'].company_id))


async def test_seven_formats_refresh_private_download_and_mixed_image(setup):
    settings, sessions, users, c = setup
    conv = await conversation(c['employee'])
    # Office archives embed timestamps; compare downloads with the uploaded bytes.
    originals = samples()
    docs = [await upload(c['employee'], name, data) for name, data in originals.items()]
    raw = io.BytesIO(); Image.new('RGB', (2, 2)).save(raw, 'PNG')
    image = await upload(c['employee'], 'image.png', raw.getvalue(), 'image/png')
    for group in (docs[:4], [*docs[4:], image]):
        payload = {'conversationId': conv['id'], 'text': '查看材料', 'attachmentIds': [d['id'] for d in group]}
        headers = keyed()
        first = await c['employee'].post('/api/v1/messages', json=payload, headers=headers)
        assert first.status_code == 202, first.text
        duplicate = await c['employee'].post('/api/v1/messages', json=payload, headers=headers)
        assert duplicate.json() == first.json()
        await run(settings, sessions, users, first.json(), document_model())
        data = (await c['employee'].get('/api/v1/messages/' + first.json()['messageId'])).json()
        assert data['job']['state'] == 'awaiting_input', data
        for item in group:
            response = await c['employee'].get(item['url'])
            assert response.status_code == 200
            if item['kind'] == 'document':
                assert response.content == originals[item['name']]
                assert response.headers['Content-Disposition'].startswith('attachment;')
                extracted = (await c['employee'].get(f"/api/v1/uploads/{item['id']}/extraction")).json()
                assert extracted['attachment']['extraction']['status'] == 'ready' and extracted['items']
                assert all('text' not in attached for attached in data['attachments'])


async def test_filename_and_upload_boundaries(setup):
    settings, sessions, users, c = setup
    item = await upload(c['employee'], '..\\dir/恶意\r\n名字.txt', b'safe text', 'text/plain')
    assert '\r' not in item['name'] and '/' not in item['name'] and '\\' not in item['name']
    assert (settings.media_dir / item['id']).read_bytes() == b'safe text'
    assert (await c['employee'].get(item['url'])).status_code == 200
    for name, data, mime in [('old.doc', b'old', 'application/msword'), ('fake.pdf', b'not pdf', 'application/pdf'), ('fake.txt', b'text', 'image/png'), ('sheet.xlsx', b'PK', 'application/octet-stream'), ('unknown.exe', b'exe', 'application/octet-stream')]:
        response = await c['employee'].post('/api/v1/uploads', files={'file': (name, data, mime)})
        assert response.status_code == 415, response.text
    assert (await c['employee'].post('/api/v1/uploads', files={'file': ('large.txt', b'x' * (20 * 1024 * 1024 + 1), 'text/plain')})).status_code == 413
    conv = await conversation(c['employee'])
    docs = [await upload(c['employee'], f'large{i}.txt', b'x' * (6 * 1024 * 1024)) for i in range(4)]
    result = await c['employee'].post('/api/v1/messages', json={'conversationId': conv['id'], 'attachmentIds': [d['id'] for d in docs]}, headers=keyed())
    assert result.status_code == 422
    assert len(list(settings.media_dir.iterdir())) == 5
    long_name = await upload(c['employee'], '长' * 190 + '.TXT', b'text', 'text/plain')
    assert long_name['name'].endswith('.TXT') and len(long_name['name']) == 180
    raw = io.BytesIO(); Image.new('RGB', (2, 2)).save(raw, 'PNG')
    image = await upload(c['employee'], 'empty-mime.png', raw.getvalue(), 'application/octet-stream')
    assert image['kind'] == 'image'


async def test_agent_scope_forged_citations_and_revision_fence(setup):
    settings, sessions, users, c = setup
    owner = users['employee']
    first, second = await conversation(c['employee']), await conversation(c['employee'])
    private = await upload(c['employee'])
    sent = await message(c['employee'], first, '', [private['id']])
    await run(settings, sessions, users, sent, document_model())
    followup = await message(c['employee'], second, '另一会话')
    context = await running_context(settings, sessions, owner, followup)
    runtime = SimpleNamespace(context=context)
    assert json.loads(await find_documents.coroutine(query='', runtime=runtime))['items'] == []
    assert '不属于' in await read_document.coroutine(attachment_id=private['id'], start=0, runtime=runtime)
    async with sessions.begin() as db:
        work = WorkItem(company_id=owner.company_id, owner_id=owner.id, title='已确认材料', content={'summary': '确认事实'})
        db.add(work); await db.flush()
        db.add(WorkRevision(company_id=owner.company_id, owner_id=owner.id, work_id=work.id, revision=1, content=work.content, source_ids=[sent['messageId']]))
    data = json.loads(await read_document.coroutine(attachment_id=private['id'], start=3, runtime=runtime))
    citation = data['items'][0]['citation']
    async with sessions.begin() as db:
        answer, refs = await verified_citations(db, context, citation + '[[file:invented:1:0]]')
        assert answer == '〔1〕（来源未核实）' and refs[0]['ordinal'] == 3
    # Admin HTTP access is broader than their own assistant tool access.
    admin_conv = await conversation(c['admin']); admin_sent = await message(c['admin'], admin_conv)
    admin_context = await running_context(settings, sessions, users['admin'], admin_sent)
    assert '不属于' in await read_document.coroutine(attachment_id=private['id'], start=0, runtime=SimpleNamespace(context=admin_context))
    async with sessions.begin() as db:
        item = await db.get(Attachment, private['id']); item.extraction_revision += 1
    async with sessions() as db:
        with pytest.raises(InputChanged): await lease(db, context)


async def test_delete_during_real_extraction_cannot_publish_late_result(setup, monkeypatch):
    settings, sessions, users, c = setup
    conv = await conversation(c['employee'])
    item = await upload(c['employee'])
    sent = await message(c['employee'], conv, '', [item['id']])
    context = await running_context(settings, sessions, users['employee'], sent)
    import paa_server.documents as documents
    original = documents.parse_process
    entered, release = asyncio.Event(), asyncio.Event()
    async def delayed(*args, **kwargs):
        result = await original(*args, **kwargs)
        entered.set(); await release.wait()
        return result
    monkeypatch.setattr(documents, 'parse_process', delayed)
    task = asyncio.create_task(prepare_document(context, item['id']))
    await asyncio.wait_for(entered.wait(), 10)
    conv = (await c['employee'].get('/api/v1/conversations/' + conv['id'])).json()
    assert (await remove(c['employee'], 'conversations', conv)).status_code == 200
    release.set()
    with pytest.raises(LostLease): await task
    assert (await c['employee'].get(item['url'])).status_code == 404
    async with sessions() as db:
        assert not await db.scalar(select(DocumentChunk.id).where(DocumentChunk.attachment_id == item['id']))
        attachment = await db.get(Attachment, item['id'])
        assert attachment.deleted and attachment.extraction_status == 'deleted'
    assert not (settings.media_dir / item['id']).exists()


async def test_shared_source_retention_and_admin_purge_chunks_checkpoints(setup):
    settings, sessions, users, c = setup
    owner = users['employee']
    conv = await conversation(c['employee'])
    item = await upload(c['employee'])
    sent = await message(c['employee'], conv, '', [item['id']])
    await run(settings, sessions, users, sent, document_model())
    async with sessions.begin() as db:
        work = WorkItem(company_id=owner.company_id, owner_id=owner.id, title='确认工作', content={'summary': '保留摘要'})
        db.add(work); await db.flush()
        revision = WorkRevision(company_id=owner.company_id, owner_id=owner.id, work_id=work.id, revision=1, content=work.content, source_ids=[sent['messageId']])
        db.add(revision); await db.flush()
        reports = []
        for kind in ('daily', 'weekly'):
            report = Report(company_id=owner.company_id, owner_id=owner.id, kind=kind, period='2026-09-13', period_end='2026-09-13', timezone='Asia/Shanghai', content={'completed': '保留摘要', 'ongoing': '', 'blockers': '', 'next': ''}, source_ids=[revision.id], published_revision=1)
            db.add(report); await db.flush(); reports.append(report)
            db.add(ReportRevision(company_id=owner.company_id, owner_id=owner.id, report_id=report.id, revision=1, content=report.content, source_ids=report.source_ids))
    other_conv = await conversation(c['employee'], '其他会话读取已确认来源')
    followup = await message(c['employee'], other_conv, '引用已确认的材料')
    await run(settings, sessions, users, followup, document_model('后半部分标记'))
    assert '后半部分标记' in (await c['employee'].get('/api/v1/messages/' + followup['messageId'])).json()['reply']
    conv = (await c['employee'].get('/api/v1/conversations/' + conv['id'])).json()
    assert (await remove(c['employee'], 'conversations', conv)).status_code == 200
    assert (await c['employee'].get(item['url'])).status_code == 200
    assert (await c['employee'].get('/api/v1/uploads/' + item['id'] + '/extraction')).json()['items']
    report = (await c['employee'].get('/api/v1/reports/' + reports[0].id)).json()
    assert (await remove(c['employee'], 'reports', report)).status_code == 403
    assert (await remove(c['admin'], 'reports', report)).status_code == 200
    assert (await c['employee'].get(item['url'])).status_code == 404
    assert (await c['employee'].get('/api/v1/uploads/' + item['id'] + '/extraction')).status_code == 404
    assert (await c['admin'].get('/api/v1/reports/' + reports[1].id)).json()['content']['completed'] == '保留摘要'
    dependent = (await c['employee'].get('/api/v1/messages/' + followup['messageId'])).json()
    assert dependent['text'] == '引用已确认的材料' and dependent['reply'] == '' and dependent['citations'] == []

    async with sessions() as db:
        assert not await db.scalar(select(DocumentChunk.id).where(DocumentChunk.attachment_id == item['id']))
        assert not await db.scalar(text('SELECT COUNT(*) FROM checkpoints WHERE thread_id LIKE :prefix'), {'prefix': owner.company_id + ':' + owner.id + ':%'})


@pytest.mark.parametrize('deletion', ['report', 'conversation'])
async def test_source_deletion_purges_inflight_document_proposals(setup, deletion):
    settings, sessions, users, c = setup
    owner = users['employee']
    conv = await conversation(c['employee'])
    item = await upload(c['employee'])
    sent = await message(c['employee'], conv, '', [item['id']])
    original_context = await running_context(settings, sessions, owner, sent)
    await prepare_document(original_context, item['id'])
    other_conv = await conversation(c['employee'])
    followup = await message(c['employee'], other_conv if deletion == 'report' else conv, '从材料提取待确认工作')
    unrelated = await message(c['employee'], other_conv, '无关待处理消息')
    async with sessions.begin() as db:
        original = await db.get(Job, sent['jobId'])
        original.state, original.lease_until = 'awaiting_input', None
        work = WorkItem(company_id=owner.company_id, owner_id=owner.id, title='已确认来源', content={'summary': '保留确认摘要'})
        db.add(work); await db.flush()
        # Reports expose the original document across conversations. Conversation
        # deletion instead retains the follow-up as a confirmed business source.
        source = sent if deletion == 'report' else followup
        revision = WorkRevision(company_id=owner.company_id, owner_id=owner.id, work_id=work.id, revision=1, content=work.content, source_ids=[source['messageId']])
        db.add(revision); await db.flush()
        reports = []
        for kind in ('daily', 'weekly'):
            report = Report(company_id=owner.company_id, owner_id=owner.id, kind=kind, period='2026-09-13', period_end='2026-09-13', timezone='Asia/Shanghai', content={'completed': '保留确认摘要', 'ongoing': '', 'blockers': '', 'next': ''}, source_ids=[revision.id], published_revision=1)
            db.add(report); await db.flush(); reports.append(report)
            db.add(ReportRevision(company_id=owner.company_id, owner_id=owner.id, report_id=report.id, revision=1, content=report.content, source_ids=report.source_ids))
        unrelated_result = (await db.get(Job, unrelated['jobId'])).result
    context = await running_context(settings, sessions, owner, followup)
    runtime = SimpleNamespace(context=context)
    result = await read_document.coroutine(attachment_id=item['id'], start=3, runtime=runtime)
    assert '后半部分标记' in result
    await propose_progress.coroutine(title='来自原文件', summary='后半部分标记', status='in_progress', blocker='', next_step='', runtime=runtime)
    before = (await c['employee'].get('/api/v1/messages/' + followup['messageId'])).json()
    assert len(before['drafts']) == 1 and before['drafts'][0]['status'] == 'pending'
    assert before['suggestions'][0]['content']['summary'] == '后半部分标记'
    assert before['reply'] == '' and before['citations'] == []
    if deletion == 'report':
        target = (await c['admin'].get('/api/v1/reports/' + reports[0].id)).json()
        response = await remove(c['admin'], 'reports', target)
    else:
        target = (await c['employee'].get('/api/v1/conversations/' + conv['id'])).json()
        response = await remove(c['employee'], 'conversations', target)
    assert response.status_code == 200, response.text
    after = (await c['employee'].get('/api/v1/messages/' + followup['messageId'])).json()
    assert after['job']['state'] == 'cancelled'
    assert after['drafts'] == [] and after['suggestions'] == []
    assert after['text'] == '从材料提取待确认工作' and after['reply'] == '' and after['citations'] == []
    assert (await c['employee'].get(item['url'])).status_code == 404
    assert not (settings.media_dir / item['id']).exists()
    async with sessions() as db:
        assert (await db.get(Job, followup['jobId'])).result == {}
        draft = await db.get(ProgressDraft, before['drafts'][0]['id'])
        assert draft.status == 'deleted' and draft.content == {}
        assert not await db.scalar(select(DocumentChunk.id).where(DocumentChunk.attachment_id == item['id']))
        assert (await db.get(WorkItem, work.id)).content == work.content
        assert (await db.get(WorkRevision, revision.id)).content == revision.content
        assert (await db.get(Report, reports[1].id)).content == reports[1].content
        assert (await db.scalar(select(ReportRevision).where(ReportRevision.report_id == reports[1].id))).content == reports[1].content
        untouched = await db.get(Job, unrelated['jobId'])
        assert untouched.state == 'queued' and untouched.result == unrelated_result
        with pytest.raises(LostLease):
            await lease(db, context)


async def test_cancelled_parse_is_retryable_and_file_only_cannot_propose(setup, monkeypatch):
    settings, sessions, users, c = setup
    conv = await conversation(c['employee'])
    item = await upload(c['employee'])
    sent = await message(c['employee'], conv, '', [item['id']])
    context = await running_context(settings, sessions, users['employee'], sent)
    import paa_server.documents as documents
    entered = asyncio.Event()
    async def pending(*args, **kwargs):
        entered.set(); await asyncio.Event().wait()
    monkeypatch.setattr(documents, 'parse_process', pending)
    task = asyncio.create_task(prepare_document(context, item['id']))
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    async with sessions() as db:
        document = await db.get(Attachment, item['id'])
        assert document.extraction_status == 'failed' and '中断' in document.extraction_info['error']
    from paa_server.agent.harness import propose_progress
    result = await propose_progress.coroutine(title='自动完成', summary='文件不代表工作', status='done', blocker='', next_step='', runtime=SimpleNamespace(context=context))
    assert '询问' in result
    async with sessions() as db:
        assert (await db.get(Message, sent['messageId'])).suggestions == []


async def test_unchanged_document_checkpoint_reuses_verified_reads_on_retry(setup, monkeypatch):
    settings, sessions, users, c = setup
    conv = await conversation(c['employee'])
    item = await upload(c['employee'])
    sent = await message(c['employee'], conv, '读取后半部分', [item['id']])
    import paa_server.worker as worker
    original = worker.invoke_harness
    async def fail_after_completed_graph(*args, **kwargs):
        await original(*args, **kwargs)
        raise ValueError('fixed failure after graph')
    monkeypatch.setattr(worker, 'invoke_harness', fail_after_completed_graph)
    model = document_model('后半部分标记')
    await run(settings, sessions, users, sent, model)
    assert len(model.seen) == 1
    assert (await c['employee'].post('/api/v1/jobs/' + sent['jobId'] + '/retry', json={})).status_code == 200
    monkeypatch.setattr(worker, 'invoke_harness', original)
    await run(settings, sessions, users, sent, model)
    data = (await c['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert data['job']['state'] == 'awaiting_input', data
    assert len(model.seen) == 1  # Completed graph was reused, no second tool/model loop.
    assert data['citations'][0]['ordinal'] == 3 and '材料范围' in data['reply']
