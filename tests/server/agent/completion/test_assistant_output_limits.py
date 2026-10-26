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
from _support.agent.business_actions import runtime
from _support.agent.model_stream_errors import client_for, stream
import httpx
from _support.agent.reply_review_limits import CONFIG, response_for

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


@pytest.mark.parametrize('node_retry', [False, True])
@pytest.mark.parametrize('consumed,cap,expected', [(0, None, 8000), (3000, None, 5000), (0, 2000, 2000), (7500, 2000, 500), (8000, None, 0), (8500, None, 0)])
async def test_report_http_uses_remaining_original_task_budget(setup, monkeypatch, node_retry, consumed, cap, expected):
    from app.tasks.context import BudgetExceeded
    from app.tasks.nodes.node_execution import active_node
    context, _ = await runtime(setup, '报告输出额度')
    context.model_purpose = 'report'
    context.model_binding = {'report': {'contextCapability': {'maxOutput': cap}}}
    context.node_retry = node_retry
    if node_retry:
        await node_execution.initialize(context, 'report-output-limits')
    context.output_tokens = consumed
    async def resolve(*args):
        return {**CONFIG, 'streaming': False}, 'unused'
    monkeypatch.setattr('app.modules.model_services.bindings.resolve_bound', resolve)
    calls = []
    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body['max_tokens'] == expected
        assert body['enable_thinking'] is True and body['reasoning_effort'] == 'high'
        return response_for(body, 'ok')
    client_for(monkeypatch, respond)
    model = BoundedChatModel(model='controlled', api_key='unused', max_tokens=8000, use_responses_api=False)
    model._run_context = context
    token = active_node.set(('report-budget-test', 'review'))
    try:
        if expected:
            await model.ainvoke([HumanMessage(content='生成报告')])
            assert len(calls) == 1 and context.output_tokens == consumed + 60
        else:
            with pytest.raises(BudgetExceeded):
                await model.ainvoke([HumanMessage(content='生成报告')])
            assert not calls and context.output_tokens == consumed
    finally:
        active_node.reset(token)


async def test_report_retry_context_rejects_provider_over_task_allowance(setup, monkeypatch):
    from app.tasks.context import BudgetExceeded
    from app.tasks.nodes.node_execution import active_node
    context, _ = await runtime(setup, '报告供应商越额')
    context.model_purpose, context.node_retry = 'report', True
    await node_execution.initialize(context, 'report-overrun')
    context.output_tokens = 7990
    async def resolve(*args):
        return {**CONFIG, 'streaming': False}, 'unused'
    monkeypatch.setattr('app.modules.model_services.bindings.resolve_bound', resolve)
    calls = []
    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body['max_tokens'] == 10
        return response_for(body, 'ok')  # Provider reports 60 output tokens.
    client_for(monkeypatch, respond)
    model = BoundedChatModel(model='controlled', api_key='unused', max_tokens=8000, use_responses_api=False)
    model._run_context = context
    token = active_node.set(('report-overrun-test', 'review'))
    try:
        with pytest.raises(BudgetExceeded):
            await model.ainvoke([HumanMessage(content='生成报告')])
    finally:
        active_node.reset(token)
    assert len(calls) == 1 and context.output_tokens == 8050


async def test_report_input_reserve_and_other_internal_limits():
    from types import SimpleNamespace
    from app.agent.context.context_usage import input_budget, ensure_input
    from app.tasks.context import BudgetExceeded
    context = SimpleNamespace(model_purpose='report', model_binding={'report': {'contextCapability': {'contextWindow': 12000}}}, node_retry=True, output_tokens=0)
    reserve = output_reserve(context, 8000)
    assert reserve == 8000 and input_budget(context, reserve) == 4000
    with pytest.raises(BudgetExceeded):
        ensure_input(context, 4001, reserve)
    context.output_tokens = 3000
    assert input_budget(context, output_reserve(context, 8000)) == 7000
    context.model_purpose = 'internal'
    assert output_reserve(context, 8000) == 4000
    assert output_reserve(context, 2000) == 2000
    context.model_purpose = 'assistant'
    assert output_reserve(context, 8000) == 4000
