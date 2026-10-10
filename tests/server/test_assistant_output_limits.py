"""Exercise actual HTTP requests and accounting beyond the removed quotas."""
import json
import pytest
from langchain_core.messages import HumanMessage
from sqlalchemy import select
from app.agent.runtime.model import BoundedChatModel
from app.agent.context.context_usage import output_reserve
from app.integrations.models.chat import chat
from app.modules.model_services.models import ModelUsage
from app.tasks.nodes import node_execution
from test_business_actions import runtime
from test_model_stream_errors import client_for, stream
import httpx
from test_reply_review_limits import CONFIG, response_for

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('streaming', [True, False])
@pytest.mark.parametrize('node_retry', [True, False])
@pytest.mark.parametrize('verification', [True, False])
async def test_assistant_http_omits_limits_and_keeps_counting_over_prior_thresholds(setup, monkeypatch, streaming, node_retry, verification):
    context, _ = await runtime(setup, '长输出受控测试')
    context.node_retry = node_retry
    if node_retry:
        await node_execution.initialize(context, 'output-limits')
    context.output_tokens = 33000 if node_retry else 9000
    config = {**CONFIG, 'streaming': streaming}
    async def resolve(*args):
        return config, 'unused'
    monkeypatch.setattr('app.modules.model_services.bindings.resolve_bound', resolve)
    calls = []
    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        assert not {'max_tokens', 'max_completion_tokens', 'max_output_tokens'} & body.keys()
        # Fixed non-ASCII content exceeds both prior per-call quotas and stays
        # below the independent 16k answer / 32k JSON character boundaries.
        usage = {'prompt_tokens': 50, 'completion_tokens': 5001}
        if streaming:
            return stream({'choices': [{'delta': {'content': '长' * 5001}, 'finish_reason': 'stop'}], 'usage': usage})
        return httpx.Response(200, json={'choices': [{'message': {'role': 'assistant', 'content': '长' * 5001}, 'finish_reason': 'stop'}], 'usage': usage})
    client_for(monkeypatch, respond)
    model = BoundedChatModel(model='controlled', api_key='unused', max_tokens=None, use_responses_api=False)
    model._run_context = context
    model._verification = verification
    model._verification_reasoning = verification
    original = context.output_tokens
    for index in range(2):
        result = await model.ainvoke([HumanMessage(content=f'第{index}次')])
        assert len(result.text) == 5001
    assert len(calls) == 2 and context.output_tokens == original + 10002
    assert output_reserve(context) == 4000
    async with context.sessions() as db:
        usages = (await db.scalars(select(ModelUsage).where(ModelUsage.job_id == context.job_id))).all()
        assert len(usages) == 2 and all(row.output_tokens == row.actual_output_tokens == 5001 for row in usages)


@pytest.mark.parametrize('streaming', [True, False])
async def test_shared_chat_default_stays_bounded_and_none_strips_all_limit_fields(setup, monkeypatch, streaming):
    calls = []
    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        return response_for(body, 'ok')
    client_for(monkeypatch, respond)
    config = {**CONFIG, 'streaming': streaming}
    await chat(setup[0], config, 'unused', [{'role': 'user', 'content': 'test'}])
    assert calls[-1]['max_tokens'] == 4000
    for limit in (None, 2000):
        await chat(setup[0], {**config, 'parameters': {**config['parameters'], 'max_tokens': 1, 'max_completion_tokens': 2, 'max_output_tokens': 3}}, 'unused', [{'role': 'user', 'content': 'test'}], max_tokens=limit)
        if limit is None:
            assert not {'max_tokens', 'max_completion_tokens', 'max_output_tokens'} & calls[-1].keys()
        else:
            assert calls[-1]['max_tokens'] == 2000
