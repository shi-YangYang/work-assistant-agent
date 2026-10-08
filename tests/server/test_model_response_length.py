"""Long answers survive transport, completion decoding and the preview DTO."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.agent.completion.answer_length import check_length
from app.agent.completion.delivery import Delivery
from app.agent.runtime.reply_stream import ReplyCandidate
from app.db.base import now
from app.integrations.models.chat import chat
from app.integrations.models.transport import ProviderError
from app.tasks.feedback.reply_stream import dto
from fakes import wire_completion

pytestmark = pytest.mark.asyncio
ANSWER = '长篇正文。\n' * 6000 + '这是完整结尾。'
CONFIG = {'baseUrl': 'https://example.com/v1', 'model': 'controlled', 'streaming': True}


class Publisher:
    def __init__(self):
        self.text = ''
        self.withdrawn = False

    async def write(self, text, **options):
        self.text = text

    async def withdraw(self):
        self.withdrawn = True


def client_for(monkeypatch, *, streaming, message):
    def response(request):
        body = json.loads(request.content)
        assert not {'max_tokens', 'max_completion_tokens', 'max_output_tokens'} & body.keys()
        finish = 'tool_calls' if message.get('tool_calls') else 'stop'
        if not streaming:
            return httpx.Response(200, json={'choices': [{'message': message, 'finish_reason': finish}]})
        if finish == 'tool_calls':
            call = message['tool_calls'][0]
            arguments = call['function']['arguments']
            deltas = [{'tool_calls': [{'index': 0, **call, 'function': {**call['function'], 'arguments': ''}}]}]
            deltas.extend({'tool_calls': [{'index': 0, 'function': {'arguments': arguments[i:i + 1000]}}]}
                          for i in range(0, len(arguments), 1000))
        else:
            text = message['content']
            deltas = ([{'content': text[i:i + 1000]} for i in range(0, len(text), 1000)]
                      if isinstance(text, str) else [{'content': text}])
        events = [{'choices': [{'delta': delta}]} for delta in deltas]
        events.append({'choices': [{'delta': {}, 'finish_reason': finish}]})
        payload = ''.join('data: ' + json.dumps(event) + '\n\n' for event in events) + 'data: [DONE]\n\n'
        return httpx.Response(200, text=payload)
    monkeypatch.setattr('app.integrations.models.transport.client', lambda _: httpx.AsyncClient(transport=httpx.MockTransport(response)))


@pytest.mark.parametrize('streaming', [True, False])
@pytest.mark.parametrize('kind', ['prose', 'completion'])
async def test_long_answer_is_complete_with_provider_output_defaults(monkeypatch, streaming, kind):
    assert len(ANSWER) > 32000
    message = ({'content': ANSWER} if kind == 'prose' else wire_completion(ANSWER,
               answer_length={'quote': '至少20000字', 'unit': 'cjk_characters', 'body': ANSWER}))
    client_for(monkeypatch, streaming=streaming, message=message)
    publisher = Publisher()
    candidate = ReplyCandidate(publisher)
    result = await chat(SimpleNamespace(model_allowed_origins=()), {**CONFIG, 'streaming': streaming}, 'test',
                        [{'role': 'user', 'content': '写长文'}], max_tokens=None, text_tools=('finish_task',),
                        on_delta=candidate.feed if kind == 'completion' else None)
    received = result['choices'][0]['message']
    if kind == 'prose':
        assert received['content'] == ANSWER
    else:
        delivery = Delivery.model_validate_json(received['tool_calls'][0]['function']['arguments'])
        assert delivery.answer == delivery.answer_length.body == ANSWER
        assert check_length(delivery.answer_length, ANSWER, '写至少20000字') == ''
        if streaming:
            await candidate.finish()
            assert publisher.text == ANSWER and not publisher.withdrawn


@pytest.mark.parametrize('streaming', [True, False])
async def test_other_tool_arguments_keep_their_existing_bound(monkeypatch, streaming):
    message = wire_completion(ANSWER)
    message['tool_calls'][0]['function']['name'] = 'write_document'
    client_for(monkeypatch, streaming=streaming, message=message)
    with pytest.raises(ProviderError) as caught:
        await chat(SimpleNamespace(model_allowed_origins=()), {**CONFIG, 'streaming': streaming}, 'test',
                   [{'role': 'user', 'content': '请求'}], max_tokens=None, text_tools=('finish_task',))
    assert caught.value.code == 'invalid_response'


@pytest.mark.parametrize('streaming', [True, False])
async def test_nontext_prose_is_still_rejected(monkeypatch, streaming):
    client_for(monkeypatch, streaming=streaming, message={'content': ['invalid']})
    with pytest.raises(ProviderError) as caught:
        await chat(SimpleNamespace(model_allowed_origins=()), {**CONFIG, 'streaming': streaming}, 'test',
                   [{'role': 'user', 'content': '请求'}], max_tokens=None)
    assert caught.value.code == 'invalid_response'


async def test_preview_dto_preserves_long_text_after_access_checks(monkeypatch):
    actor = SimpleNamespace(id='user', company_id='company', active=True, role='employee')
    message = SimpleNamespace(id='message', company_id='company', owner_id='user', access={}, deleted=False)
    value = {'version': 1, 'generation': 1, 'state': 'streaming', 'text': ANSWER}
    job = SimpleNamespace(company_id='company', owner_id='user', access={}, updated_at=now(), feedback={'replyStream': value})
    valid = AsyncMock(return_value=True)
    sources = AsyncMock(return_value=False)
    monkeypatch.setattr('app.security.access.valid', valid)
    monkeypatch.setattr('app.modules.messages.service.active_message', AsyncMock(return_value=message))
    monkeypatch.setattr('app.tasks.feedback.reply_stream.validate_sources', sources)
    assert await dto(None, actor, job, message) == value
    assert valid.await_count == 2 and sources.await_count == 1
