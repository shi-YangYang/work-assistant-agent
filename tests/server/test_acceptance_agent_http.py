"""Pure HTTP-runner regressions; no DB, worker or model is used."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/company/web-acceptance'))
spec = importlib.util.spec_from_file_location('acceptance_agent_http', ROOT / 'scripts/company/web-acceptance/agent-http.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def receipt(message='root'):
    return {'messageId': message, 'jobId': 'job-' + message, 'conversationId': 'owned-conversation'}


def message(identifier='root', state='succeeded', actions=None):
    return {'id': identifier, 'job': {'id': 'job-' + identifier, 'state': state}, 'actions': actions or []}


async def no_wait(_):
    return None


@pytest.mark.asyncio
async def test_confirmation_waits_for_continuation_and_refreshes_cards(monkeypatch):
    monkeypatch.setattr(runner.asyncio, 'sleep', no_wait)
    confirmed, child_reads, events = [], [], []

    def respond(request):
        if request.method == 'POST':
            confirmed.append(json.loads(request.content)['expectedRevision'])
            return httpx.Response(200, json={'id': 'action', 'state': 'succeeded', 'continuation': receipt('child')})
        if request.url.path.endswith('/child'):
            child_reads.append(True)
            return httpx.Response(200, json=message('child', 'running' if len(child_reads) == 1 else 'succeeded'))
        card = {'id': 'action', 'state': 'pending', 'revision': 7, 'canConfirm': True}
        if confirmed:
            card.update(state='succeeded', continuation=receipt('child'))
        return httpx.Response(200, json=message(actions=[card]))

    async with httpx.AsyncClient(base_url='http://owned', transport=httpx.MockTransport(respond)) as client:
        value, approvals = await runner.settle(client, receipt(), 1, approve=True, progress=events.append)
    assert value['id'] == 'child'
    assert confirmed == [7]
    assert len(child_reads) == 2
    assert [item['id'] for item in approvals] == ['action']
    assert [item['receipt']['messageId'] for item in events if item['kind'] == 'continuation'] == ['child']


@pytest.mark.asyncio
async def test_existing_continuation_is_observed_without_reconfirming(monkeypatch):
    monkeypatch.setattr(runner.asyncio, 'sleep', no_wait)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=message('child') if request.url.path.endswith('/child') else message(actions=[{'id': 'done', 'state': 'succeeded', 'continuation': receipt('child')}]))

    async with httpx.AsyncClient(base_url='http://owned', transport=httpx.MockTransport(respond)) as client:
        value, approvals = await runner.settle(client, receipt(), 1, approve=True)
    assert value['id'] == 'child'
    assert not approvals
    assert all(request.method == 'GET' for request in requests)


@pytest.mark.asyncio
async def test_unapproved_pending_card_and_plain_legacy_reply_do_not_mutate():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=message(actions=[{'id': 'pending', 'state': 'pending', 'canConfirm': True, 'revision': 1}]))

    async with httpx.AsyncClient(base_url='http://owned', transport=httpx.MockTransport(respond)) as client:
        value, approvals = await runner.settle(client, receipt(), 1)
    assert value['id'] == 'root'
    assert not approvals
    assert len(requests) == 1 and requests[0].method == 'GET'


@pytest.mark.asyncio
async def test_continuation_cannot_escape_conversation():
    bad = {**receipt('child'), 'conversationId': 'unrelated'}
    async with httpx.AsyncClient(base_url='http://owned', transport=httpx.MockTransport(lambda request: httpx.Response(200, json=message(actions=[{'id': 'a', 'state': 'succeeded', 'continuation': bad}])))) as client:
        with pytest.raises(RuntimeError, match='left the accepted conversation'):
            await runner.settle(client, receipt(), 1)


@pytest.mark.asyncio
@pytest.mark.parametrize('count', [1, 2])
async def test_unrecorded_admission_is_read_back_or_ambiguity_stops(tmp_path, count):
    messages = [{'id': 'accepted-' + str(i), 'text': 'frozen synthetic turn', 'replyTo': None, 'job': {'id': 'job-' + str(i)}} for i in range(count)]
    case = {'turns': ['completed turn', 'frozen synthetic turn']}
    async with httpx.AsyncClient(base_url='http://owned', transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'items': messages, 'nextCursor': None}))) as client:
        if count == 2:
            with pytest.raises(RuntimeError, match='Ambiguous'):
                await runner.recover_receipt(client, case, 1, 'owned-conversation', tmp_path, [])
        else:
            value = await runner.recover_receipt(client, case, 1, 'owned-conversation', tmp_path, [])
            assert value['messageId'] == 'accepted-0'


@pytest.mark.asyncio
async def test_durable_admission_wins_without_another_request(tmp_path):
    runner.append_row(tmp_path / 'accepted.jsonl', {'turn': 2, 'receipt': receipt('existing')})
    async with httpx.AsyncClient(base_url='http://owned', transport=httpx.MockTransport(lambda request: pytest.fail('must not request'))) as client:
        assert await runner.recover_receipt(client, {'turns': ['a', 'b']}, 1, None, tmp_path, []) == receipt('existing')


@pytest.mark.asyncio
async def test_cancellation_after_admission_keeps_receipt(tmp_path, monkeypatch):
    real_client = httpx.AsyncClient

    def respond(request):
        if request.url.path.endswith('/login'):
            return httpx.Response(200, json={'csrf': 'test'})
        if request.url.path.endswith('/execution-settings'):
            return httpx.Response(200, json={'executionMode': 'auto'})
        if request.url.path.endswith('/messages'):
            return httpx.Response(202, json=receipt())
        pytest.fail(request.url.path)

    async def snapshot(_):
        return {}

    async def interrupted(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(runner.httpx, 'AsyncClient', lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(runner, 'snapshot', snapshot)
    monkeypatch.setattr(runner, 'settle', interrupted)
    state = {'apiOrigin': 'http://owned', 'origin': 'http://owned', 'users': {'realEmployee': {'username': 'synthetic', 'password': 'test'}}}
    with pytest.raises(asyncio.CancelledError):
        await runner.execute_case({'id': 'synthetic', 'role': 'realEmployee', 'mode': 'auto', 'turns': ['synthetic']}, state, tmp_path, tmp_path, 1)
    assert runner.read_rows(tmp_path / 'synthetic/accepted.jsonl')[0]['receipt'] == receipt()
    assert not (tmp_path / 'synthetic/first.jsonl').exists()


@pytest.mark.asyncio
async def test_continuation_skips_completed_turn_and_recovers_accepted_turn_without_writes(tmp_path, monkeypatch):
    previous, output = tmp_path / 'prior', tmp_path / 'continued'
    previous.mkdir(); output.mkdir()
    original = {'case': 'synthetic', 'turn': 1, 'receipt': receipt(), 'message': message()}
    runner.append_row(previous / 'first.jsonl', original)
    (previous / 'before.json').write_text('{}')
    frozen_evidence = (previous / 'first.jsonl').read_bytes()
    real_client, posts, observed = httpx.AsyncClient, [], []

    def respond(request):
        if request.method != 'GET':
            posts.append(request.url.path)
        if request.url.path.endswith('/login'):
            return httpx.Response(200, json={'csrf': 'test'})
        if request.url.path.endswith('/logout'):
            return httpx.Response(200, json={})
        if request.url.path.endswith('/execution-settings'):
            return httpx.Response(200, json={'executionMode': 'auto'})
        pytest.fail(request.url.path)

    async def settle(client, accepted, timeout, **kwargs):
        observed.append(accepted['messageId'])
        return message(accepted['messageId']), []

    async def recover(*args):
        return receipt('already-admitted')

    async def snapshot(_):
        return {}

    monkeypatch.setattr(runner.httpx, 'AsyncClient', lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(runner, 'settle', settle)
    monkeypatch.setattr(runner, 'recover_receipt', recover)
    monkeypatch.setattr(runner, 'snapshot', snapshot)
    state = {'apiOrigin': 'http://owned', 'origin': 'http://owned', 'users': {'realEmployee': {'username': 'synthetic', 'password': 'test'}}}
    case = {'id': 'synthetic', 'role': 'realEmployee', 'mode': 'auto', 'turns': ['previous', 'remaining'], 'workFixtures': [{'title': 'must not reseed'}]}
    result = await runner.execute_case(case, state, output, tmp_path, 1, previous=previous)
    assert posts == ['/api/v1/auth/login', '/api/v1/auth/logout']
    assert observed == ['root', 'already-admitted']
    assert [row['turn'] for row in result['turns']] == [1, 2]
    assert [row['turn'] for row in runner.read_rows(output / 'synthetic/first.jsonl')] == [2]
    assert result['turns'][1]['recoveredAdmission'] is True
    assert (previous / 'first.jsonl').read_bytes() == frozen_evidence
