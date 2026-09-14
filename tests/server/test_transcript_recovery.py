"""Corrected voice inputs through the real API, graph and PostgreSQL checkpoint."""
import hashlib

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import select

from paa_server import worker
from paa_server.agent.harness import ToolBoundary
from paa_server.models import Attachment, Job, Message, ProgressDraft, WorkItem, WorkRevision
from paa_server.worker import claim, process_job
from test_company import keyed, send
from test_recovery import RecoveryModel

pytestmark = pytest.mark.asyncio
OLD = '项目已全部完成'
CORRECTED = '项目尚未完成，仅初稿完成'


class TranscriptModel(RecoveryModel):
    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        current = next(m for m in reversed(messages) if isinstance(m, HumanMessage))
        self.seen.append(str(current.content))
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError('Controlled failure before the first model result')
        summary = CORRECTED if CORRECTED in str(current.content) else OLD
        if isinstance(messages[-1], ToolMessage):
            answer = AIMessage(content=summary)
        else:
            answer = AIMessage(content='', tool_calls=[{'id': 'voice-progress', 'name': 'propose_progress', 'args': {'title': '语音项目', 'summary': summary, 'status': 'in_progress' if summary == CORRECTED else 'done', 'blocker': '', 'next_step': '', 'work_id': None}}])
        return ChatResult(generations=[ChatGeneration(message=answer)])


def transcript_model(*, fail_once=False):
    return TranscriptModel(model='controlled-transcript', api_key='no-network', base_url='http://127.0.0.1:1', max_retries=0, label='voice', fail_once=fail_once)


async def voice_message(setup):
    settings, sessions, users, clients = setup
    actor = users['employee']
    raw = b'controlled original audio; decoding is outside this recovery regression'
    async with sessions.begin() as db:
        attachment = Attachment(company_id=actor.company_id, owner_id=actor.id, kind='audio', mime='audio/wav', name='controlled.wav', size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        db.add(attachment)
        await db.flush()
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    (settings.media_dir / attachment.id).write_bytes(raw)
    result = await send(clients['employee'], '', [attachment.id])
    return result, attachment.id, raw


async def correct(client, message_id, revision):
    response = await client.patch(f'/api/v1/messages/{message_id}/transcript', json={'text': CORRECTED, 'expectedRevision': revision})
    assert response.status_code == 200, response.text
    assert response.json()['transcriptRevision'] == revision + 1


async def original_asr(context, attachment):
    return OLD


async def retry(client, sessions, actor, job_id):
    response = await client.post(f'/api/v1/jobs/{job_id}/retry', json={})
    assert response.status_code == 200, response.text
    job = await claim(sessions, actor.id)
    assert job.id == job_id
    return job


@pytest.mark.parametrize('failure', ['model', 'pending_tool', 'completed'])
async def test_corrected_transcript_restarts_old_checkpoint_and_reuses_new_completion(setup, monkeypatch, failure):
    settings, sessions, users, clients = setup
    actor, client = users['employee'], clients['employee']
    result, attachment_id, raw = await voice_message(setup)
    original_boundary = ToolBoundary.awrap_tool_call
    original_invoke = worker.invoke_harness

    async def fail_before_tool(self, request, handler):
        raise RuntimeError('Controlled pending tool failure')

    async def fail_after_completion(*args, **kwargs):
        await original_invoke(*args, **kwargs)
        raise RuntimeError('Controlled failure after graph completion')

    if failure == 'pending_tool':
        monkeypatch.setattr(ToolBoundary, 'awrap_tool_call', fail_before_tool)
    elif failure == 'completed':
        monkeypatch.setattr(worker, 'invoke_harness', fail_after_completion)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        job = await claim(sessions, actor.id)
        await process_job(job, sessions, settings, saver, model=transcript_model(fail_once=failure == 'model'), asr_provider=original_asr)
        monkeypatch.setattr(ToolBoundary, 'awrap_tool_call', original_boundary)
        monkeypatch.setattr(worker, 'invoke_harness', original_invoke)
        message = (await client.get('/api/v1/messages/' + result['messageId'])).json()
        assert message['job']['state'] == 'failed' and message['transcriptRevision'] == 1
        assert [d['content']['summary'] for d in message['drafts']] == ([OLD] if failure == 'completed' else [])
        original_suggestions = message['suggestions']
        if failure == 'completed':
            draft = message['drafts'][0]
            confirmed = await client.post('/api/v1/progress-drafts/confirm', json={'items': [{'id': draft['id'], 'expectedRevision': draft['revision']}]}, headers=keyed())
            assert confirmed.status_code == 200
            original_suggestions = (await client.get('/api/v1/messages/' + result['messageId'])).json()['suggestions']
        await correct(client, result['messageId'], 1)
        job = await retry(client, sessions, actor, result['jobId'])
        revised_model = transcript_model()
        await process_job(job, sessions, settings, saver, model=revised_model)
        assert revised_model.calls == 2
        assert all(CORRECTED in value and OLD not in value for value in revised_model.seen)
        message = (await client.get('/api/v1/messages/' + result['messageId'])).json()
        assert message['job']['state'] == 'succeeded' and message['reply'] == CORRECTED
        assert [d['content']['summary'] for d in message['drafts'] if d['status'] == 'pending'] == [CORRECTED]
        assert message['suggestions'][:len(original_suggestions)] == original_suggestions
        async with sessions() as db:
            source = await db.get(Message, result['messageId'])
            assert source.transcript_history[-1]['text'] == OLD
            if failure == 'completed':
                work = await db.scalar(select(WorkItem).where(WorkItem.owner_id == actor.id))
                revision = await db.scalar(select(WorkRevision).where(WorkRevision.work_id == work.id))
                assert work.revision == 1 and work.content['summary'] == revision.content['summary'] == OLD
        assert (settings.media_dir / attachment_id).read_bytes() == raw
        # Simulate losing only the final worker commit for the corrected input.
        # Retrying the same source must reuse this input's completed graph exactly.
        async with sessions.begin() as db:
            (await db.get(Job, result['jobId'])).state = 'failed'
        unchanged = transcript_model(fail_once=True)
        job = await retry(client, sessions, actor, result['jobId'])
        await process_job(job, sessions, settings, saver, model=unchanged)
        assert unchanged.calls == 0
        again = (await client.get('/api/v1/messages/' + result['messageId'])).json()
        assert again['job']['state'] == 'succeeded' and again['suggestions'] == message['suggestions']


async def test_unchanged_input_resumes_pending_tool_idempotently_before_and_after_correction(setup, monkeypatch):
    settings, sessions, users, clients = setup
    actor, client = users['employee'], clients['employee']
    result, _, _ = await voice_message(setup)
    original = ToolBoundary.awrap_tool_call

    async def fail_after_tool(self, request, handler):
        await original(self, request, handler)
        raise RuntimeError('Controlled failure after the committed tool write')

    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        job = await claim(sessions, actor.id)
        for revision, expected in ((1, OLD), (2, CORRECTED)):
            monkeypatch.setattr(ToolBoundary, 'awrap_tool_call', fail_after_tool)
            await process_job(job, sessions, settings, saver, model=transcript_model(), asr_provider=original_asr)
            monkeypatch.setattr(ToolBoundary, 'awrap_tool_call', original)
            job = await retry(client, sessions, actor, result['jobId'])
            resumed = transcript_model()
            await process_job(job, sessions, settings, saver, model=resumed)
            assert resumed.calls == 1 and expected in resumed.seen[0]
            async with sessions() as db:
                drafts = (await db.scalars(select(ProgressDraft).where(ProgressDraft.message_id == result['messageId']))).all()
                assert len(drafts) == revision
                assert sum(d.content['summary'] == expected for d in drafts) == 1
            if revision == 1:
                # A crash after completion still exposes retry; correction chooses
                # a new checkpoint without changing the earlier draft snapshot.
                async with sessions.begin() as db:
                    (await db.get(Job, result['jobId'])).state = 'failed'
                await correct(client, result['messageId'], 1)
                job = await retry(client, sessions, actor, result['jobId'])


@pytest.mark.parametrize('point', ['tool_write', 'reply_write'])
async def test_correction_during_processing_blocks_late_writes_and_allows_retry(setup, monkeypatch, point):
    settings, sessions, users, clients = setup
    actor, client = users['employee'], clients['employee']
    result, _, _ = await voice_message(setup)
    original_boundary, original_invoke = ToolBoundary.awrap_tool_call, worker.invoke_harness
    changed = False

    async def correct_after_boundary(self, request, handler):
        async def correct_then_write(inner):
            nonlocal changed
            if not changed:
                changed = True
                await correct(client, result['messageId'], 1)
            return await handler(inner)
        return await original_boundary(self, request, correct_then_write)

    async def correct_after_graph(*args, **kwargs):
        answer = await original_invoke(*args, **kwargs)
        await correct(client, result['messageId'], 1)
        return answer

    if point == 'tool_write':
        monkeypatch.setattr(ToolBoundary, 'awrap_tool_call', correct_after_boundary)
    else:
        monkeypatch.setattr(worker, 'invoke_harness', correct_after_graph)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(await claim(sessions, actor.id), sessions, settings, saver, model=transcript_model(), asr_provider=original_asr)
        message = (await client.get('/api/v1/messages/' + result['messageId'])).json()
        assert message['job']['state'] == 'failed' and '已被纠正' in message['job']['error']
        assert not message['reply']
        assert len(message['drafts']) == (1 if point == 'reply_write' else 0)
        monkeypatch.setattr(ToolBoundary, 'awrap_tool_call', original_boundary)
        monkeypatch.setattr(worker, 'invoke_harness', original_invoke)
        revised = transcript_model()
        await process_job(await retry(client, sessions, actor, result['jobId']), sessions, settings, saver, model=revised)
        assert all(CORRECTED in value and OLD not in value for value in revised.seen)
        message = (await client.get('/api/v1/messages/' + result['messageId'])).json()
        assert message['job']['state'] == 'succeeded' and message['reply'] == CORRECTED


async def test_correction_during_asr_binds_the_selected_text_and_revision(setup):
    settings, sessions, users, clients = setup
    actor, client = users['employee'], clients['employee']
    result, _, _ = await voice_message(setup)

    async def late_asr(context, attachment):
        await correct(client, result['messageId'], 0)
        return OLD

    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        selected = transcript_model()
        await process_job(await claim(sessions, actor.id), sessions, settings, saver, model=selected, asr_provider=late_asr)
        assert all(CORRECTED in value and OLD not in value for value in selected.seen)
        message = (await client.get('/api/v1/messages/' + result['messageId'])).json()
        assert message['job']['state'] == 'succeeded'
        assert message['transcriptRevision'] == 1 and message['transcript'] == message['reply'] == CORRECTED
        async with sessions.begin() as db:
            (await db.get(Job, result['jobId'])).state = 'failed'
        unchanged = transcript_model(fail_once=True)
        await process_job(await retry(client, sessions, actor, result['jobId']), sessions, settings, saver, model=unchanged)
        assert unchanged.calls == 0
