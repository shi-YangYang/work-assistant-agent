"""Owned benchmark captures parsed public failures without changing the adapter."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import Settings
from app.integrations.models import chat
from app.integrations.models.stream_events import ModelDelta, ToolDelta
from app.integrations.models.transport import ProviderError
from _support.agent.model_stream_errors import client_for, stream


def observer():
    path = Path(__file__).resolve().parents[3] / 'scripts/benchmarks/assistant-latency-runtime.py'
    spec = importlib.util.spec_from_file_location('latency_runtime_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['arguments', 'sse', 'nonstream'])
async def test_real_adapter_failure_keeps_only_public_parsed_deltas(monkeypatch, failure):
    module, rows, forwarded = observer(), [], []
    public = {'choices': [{'delta': {'content': '公开回答', 'reasoning_content': 'PRIVATE_REASONING',
                'tool_calls': [{'index': 0, 'id': 'call_x', 'function': {'name': 'finish_task', 'arguments': '{"answer":'}}]}}]}
    if failure == 'arguments':
        response = stream(public, {'choices': [{'delta': {}, 'finish_reason': 'tool_calls'}]})
    elif failure == 'sse':
        response = httpx.Response(200, text='data: ' + json.dumps(public) + '\n\ndata: invalid-json\n\n', headers={'Content-Type': 'text/event-stream'})
    else:
        response = httpx.Response(200, text='invalid-json')
    client_for(monkeypatch, lambda _: response)
    trace = SimpleNamespace(emit=lambda kind, **values: rows.append({'kind': kind, **values}))
    async def delta(value):
        forwarded.append(value)
    observed = module.observed_chat_call(chat._chat, trace)
    with pytest.raises(ProviderError):
        await observed(Settings(), {'baseUrl': 'https://api.openai.com/v1', 'model': 'test', 'streaming': failure != 'nonstream'}, 'provider-secret', [], on_delta=delta)
    assert len(rows) == 1 and rows[0]['kind'] == 'wire_failure' and rows[0]['requestId']
    assert rows[0]['diagnostic'] == {'arguments': 'tool_arguments_json', 'sse': 'stream_json', 'nonstream': 'response_json'}[failure]
    raw = json.dumps(rows, ensure_ascii=False)
    assert 'PRIVATE_REASONING' not in raw and 'provider-secret' not in raw
    assert not rows[0]['truncated'] and module.REQUEST_ID.get() is None
    if failure != 'nonstream':
        assert len(forwarded) == 1 and rows[0]['deltas'][0]['content'] == '公开回答'
        assert rows[0]['deltas'][0]['tools'][0]['arguments'] == '{"answer":'
    else:
        assert rows[0]['deltas'] == []


@pytest.mark.asyncio
async def test_failure_bound_secret_split_and_original_exception():
    module, rows = observer(), []
    error = RuntimeError('do not log this exception message')
    async def failing(*args, **kwargs):
        await kwargs['on_delta'](ModelDelta('provider-'))
        await kwargs['on_delta'](ModelDelta('secret'))
        await kwargs['on_delta'](ModelDelta('x' * (module.MAX_FAILURE_CHARS + 1)))
        raise error
    trace = SimpleNamespace(emit=lambda kind, **values: rows.append(values))
    with pytest.raises(RuntimeError) as actual:
        await module.observed_chat_call(failing, trace)(None, {}, 'provider-secret', [])
    assert actual.value is error
    assert rows[0]['truncated'] and rows[0]['omittedDeltas'] == 1
    assert rows[0]['capturedChars'] <= module.MAX_FAILURE_CHARS
    assert ''.join(item['content'] for item in rows[0]['deltas']) == '*' * len('provider-secret')
    assert 'do not log' not in json.dumps(rows)


@pytest.mark.asyncio
async def test_observer_write_error_does_not_replace_provider_failure():
    module = observer()
    error = ProviderError('invalid_response', 'original')
    async def failing(*args, **kwargs):
        raise error
    def emit(*args, **kwargs):
        raise OSError('private path omitted')
    with pytest.raises(ProviderError) as actual:
        await module.observed_chat_call(failing, SimpleNamespace(emit=emit))(None, {}, '', [])
    assert actual.value is error and module.REQUEST_ID.get() is None
