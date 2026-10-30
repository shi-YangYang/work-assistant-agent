"""Keep upstream failure evidence internally without changing public failures."""
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.db.base import now
from app.integrations.models.chat import chat
from app.integrations.models.diagnostics import MAX_DETAIL_CHARS
from app.integrations.models.transport import ProviderError, status_error
from app.modules.model_services.models import ModelUsage
from app.modules.model_services.usage.usage import RequestRecord, dto
from app.tasks.nodes.node_failures import classify
from app.tasks.timing import Timing
from _support.agent.model_stream_errors import client_for, stream


pytestmark = pytest.mark.asyncio
KEY = 'synthetic-provider-credential'
CONFIG = {'baseUrl': 'https://example.com/v1', 'model': 'controlled', 'streaming': True, 'parameters': {}}
SETTINGS = SimpleNamespace(model_allowed_origins=())


def diagnostics(caplog):
    return [json.loads(record.message.removeprefix('model.upstream_error ')) for record in caplog.records
            if record.name == 'paa.model_diagnostics']


@pytest.mark.parametrize('mode,category', [('http', 'network'), ('json', 'provider_error'), ('sse', 'provider_error')])
async def test_failure_details_retained_only_in_internal_channels(monkeypatch, caplog, mode, category):
    payload = {'error': {'code': 'gateway_unknown', 'type': 'provider_fault',
                         'message': 'Upstream shard unavailable: ' + KEY,
                         'apiKey': 'another-credential',
                         'details': {'request': {'messages': ['echoed-prompt']}}},
               'request_id': 'upstream-body-id',
               'choices': [{'delta': {'content': 'private-answer', 'reasoning_content': 'private-reasoning'}}]}
    calls = []
    def respond(request):
        calls.append(request)
        response = stream(payload) if mode == 'sse' else httpx.Response(503 if mode == 'http' else 200, json=payload)
        response.headers['x-request-id'] = 'req_upstream_12345678'
        response.headers['set-cookie'] = 'secret-session-cookie'
        return response
    client_for(monkeypatch, respond)
    caplog.set_level(logging.INFO, logger='paa.latency')
    timing = Timing('job-upstream', 2, 3)
    with pytest.raises(ProviderError) as failure:
        with timing.span('model', call='usage-call', kind='main'):
            await chat(SETTINGS, {**CONFIG, 'streaming': mode != 'json'}, KEY,
                       [{'role': 'user', 'content': 'private-prompt'}], on_timing=timing.mark)
    error = failure.value
    assert len(calls) == 1 and error.code == category
    records = diagnostics(caplog)
    assert len(records) == 1
    record = records[0]
    assert record == error.upstream_diagnostic
    assert record['source'] == mode and record['http_status'] == (503 if mode == 'http' else 200)
    assert record['provider_request_id'] == 'req_upstream_12345678'
    detail = json.loads(record['detail'])
    assert detail['error']['code'] == 'gateway_unknown' and detail['error']['type'] == 'provider_fault'
    assert detail['error']['message'] == 'Upstream shard unavailable: [redacted]'
    assert detail['request_id'] == 'upstream-body-id' and record['truncated'] is False
    events = [json.loads(record.message.removeprefix('latency ')) for record in caplog.records
              if record.name == 'paa.latency' and 'model.upstream_error' in record.message]
    assert len(events) == 1 and events[0]['diagnostic_id'] == record['diagnostic_id']
    assert events[0]['job'] == 'job-upstream' and events[0]['parent_call'] == 'usage-call'
    assert 'detail' not in events[0] and 'Upstream shard' not in json.dumps(events)
    for private in (KEY, 'another-credential', 'secret-session-cookie', 'echoed-prompt', 'private-answer', 'private-reasoning', 'private-prompt'):
        assert private not in caplog.text
    assert 'Upstream shard' not in str(error) and 'gateway_unknown' not in classify(error).message

    # Exercise the actual persistence/DTO boundary with a controlled DB session;
    # only the fixed safe exception message may become user-visible usage data.
    row = ModelUsage(id='usage-call', status='running', started_at=now(), created_at=now())
    db = AsyncMock()
    db.scalar.return_value = row
    transaction = AsyncMock()
    transaction.__aenter__.return_value = db
    sessions = MagicMock()
    sessions.begin.return_value = transaction
    await RequestRecord(sessions, row.id).finish(error)
    public = json.dumps(dto(row), ensure_ascii=False)
    assert row.status == 'failed' and row.error_code == category
    assert row.error_message == str(error)
    assert 'Upstream shard' not in public and 'gateway_unknown' not in public and record['diagnostic_id'] not in public


async def test_http_text_errors_are_saved_without_credentials_or_timing_callback(monkeypatch, caplog):
    body = 'Gateway refused upstream connection\nBearer other-token\npassword=top-secret-value\n' + KEY
    client_for(monkeypatch, lambda _: httpx.Response(502, text=body))
    with pytest.raises(ProviderError) as failure:
        await chat(SETTINGS, CONFIG, KEY, [])
    assert failure.value.code == 'network'
    record = diagnostics(caplog)[0]
    assert 'Gateway refused upstream connection' in record['detail']
    assert all(secret not in caplog.text for secret in (KEY, 'other-token', 'top-secret-value'))
    assert str(failure.value) == '模型服务暂不可用，请稍后重试'


async def test_diagnostic_is_bounded_and_redacts_before_truncation(monkeypatch, caplog):
    payload = {'error': {'code': 'unknown', 'message': 'x' * (MAX_DETAIL_CHARS - 50) + KEY + 'y' * MAX_DETAIL_CHARS}}
    client_for(monkeypatch, lambda _: stream(payload))
    with pytest.raises(ProviderError):
        await chat(SETTINGS, CONFIG, KEY, [])
    record = diagnostics(caplog)[0]
    assert record['truncated'] and len(record['detail']) == MAX_DETAIL_CHARS
    assert 'synthetic-provider' not in record['detail'] and KEY not in caplog.text


async def test_credential_echo_in_request_identifier_is_also_redacted(monkeypatch, caplog):
    key = 'req_synthetic_credential'
    client_for(monkeypatch, lambda _: httpx.Response(401, json={'error': {'message': 'Invalid credential'}},
                                                    headers={'x-request-id': key}))
    caplog.set_level(logging.INFO, logger='paa.latency')
    with pytest.raises(ProviderError):
        await chat(SETTINGS, CONFIG, key, [], on_timing=Timing('redaction').mark)
    assert diagnostics(caplog)[0]['provider_request_id'] == '[redacted]'
    assert key not in caplog.text


async def test_required_compatibility_fallback_records_rejection_once(monkeypatch, caplog):
    calls, retried = [], []
    def respond(request):
        calls.append(json.loads(request.content)['tool_choice'])
        if len(calls) == 1:
            return httpx.Response(400, json={'error': {'message': 'tool_choice required is unsupported ' + KEY}})
        return stream({'choices': [{'delta': {'content': '完成'}, 'finish_reason': 'stop'}]})
    async def on_retry(error):
        retried.append(error)
    client_for(monkeypatch, respond)
    result = await chat(SETTINGS, CONFIG, KEY, [], tool_choice='required', on_retry=on_retry)
    assert result['choices'][0]['message']['content'] == '完成'
    assert calls == ['required', 'auto'] and len(retried) == 1
    assert retried[0].code == 'tool_choice_unsupported'
    assert diagnostics(caplog) == [retried[0].upstream_diagnostic]
    assert 'tool_choice required is unsupported' in diagnostics(caplog)[0]['detail'] and KEY not in caplog.text


@pytest.mark.parametrize('read_body', [True, False])
async def test_shared_http_error_capture_keeps_authentication_classification(caplog, read_body):
    response = httpx.Response(401, **({'json': {'error': {'message': 'Account suspended'}}} if read_body else {'stream': httpx.ByteStream(b'')}))
    with pytest.raises(ProviderError) as failure:
        status_error(response)
    assert failure.value.code == 'authentication' and failure.value.status == 401
    record = diagnostics(caplog)[0]
    assert ('Account suspended' if read_body else 'response body not read') in record['detail']
