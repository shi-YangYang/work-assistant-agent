"""Exhausted reasoning must not starve or bypass the complete reply verdict."""
import json
from copy import deepcopy

import httpx
import pytest
from sqlalchemy import select

from app.agent.completion.reply_review import review_reply
from app.modules.model_services.models import ModelUsage
from app.tasks.models import Job
from app.tasks.nodes import node_execution
from fakes import set_delivery
from test_business_actions import runtime
from test_model_stream_errors import client_for, stream
from test_task_retry import fast_nodes

pytestmark = pytest.mark.asyncio
CONFIG = {'baseUrl': 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'model': 'deepseek-v4.1-flash',
          'streaming': True, 'parameters': {'enable_thinking': True, 'reasoning_effort': 'high', 'temperature': .3}}
WRONG = '总共80件，甲50件、乙40件，恰好分完。'
ANSWER = '# 会议安排\n' + '提前准备议程，会后记录结论。\n' * 90 + WRONG


def response_for(body, content, finish='stop'):
    # Complete-looking JSON is still invalid when the provider reports length.
    message = {'content': content, 'reasoning_content': 'private reasoning'}
    usage = {'prompt_tokens': 2100, 'completion_tokens': body['max_tokens'] if finish == 'length' else 60,
             'completion_tokens_details': {'reasoning_tokens': body['max_tokens'] if finish == 'length' else 0}}
    if body['stream']:
        return stream({'choices': [{'delta': message, 'finish_reason': finish}], 'usage': usage})
    return httpx.Response(200, json={'choices': [{'message': {'role': 'assistant', **message}, 'finish_reason': finish}], 'usage': usage})


async def configure(setup, monkeypatch, *, streaming=True, retry=True, base=None):
    context, _ = await runtime(setup, '请核对文章中的数量关系，不要写入工作。')
    context.node_retry = retry
    await node_execution.initialize(context, 'review-output-budget')
    await set_delivery(context, ANSWER)
    original = deepcopy(CONFIG)
    original['streaming'] = streaming
    if base:
        original['baseUrl'] = base
    preserved = deepcopy(original)
    async def resolve(*args):
        return original, 'unused'
    monkeypatch.setattr('app.modules.model_services.bindings.resolve_bound', resolve)
    return context, original, preserved


@pytest.mark.parametrize('streaming', [True, False])
@pytest.mark.parametrize('scope', ['numeric', 'facts', 'business'])
async def test_review_recovers_output_limit_in_existing_retry_and_still_reports_real_issue(setup, fast_nodes, monkeypatch, streaming, scope):
    context, original, preserved = await configure(setup, monkeypatch, streaming=streaming)
    if scope == 'facts':
        context.delivery = {**context.delivery, 'verification_requested': True, 'verification_quote': '请核对文章中的数量关系'}
        context.reply_evidence = [{'id': 1, 'tool': 'web_fetch', 'result': '甲50件、乙40件，共90件。'}]
    calls = []
    verdict = {'issues': [{'kind': 'fact', 'quote': WRONG, 'reason': '50加40为90，与总数80矛盾。', 'evidence': [1] if scope == 'facts' else []}]}
    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            return response_for(body, '{"issues":[]}', 'length')
        return response_for(body, json.dumps(verdict, ensure_ascii=False))
    client_for(monkeypatch, respond)
    options = {'business': scope == 'business', 'quantitative': {'kind': 'quantitative_consistency'}}
    result = await review_reply(context, ANSWER, **options)
    assert result.verified and result.needs_response and WRONG not in result.text and not result.needs_action
    assert result.text.startswith('# 会议安排') and len(calls) == context.calls == 2
    first, second = calls
    assert first['enable_thinking'] is True and first['reasoning_effort'] == 'low'
    assert second['enable_thinking'] is False and 'reasoning_effort' not in second
    assert first['max_tokens'] == second['max_tokens'] == (4000 if scope == 'facts' else 2000)
    assert first['messages'] == second['messages'] and original == preserved
    payload = json.loads(second['messages'][-1]['content'])
    assert payload['answer'] == ANSWER
    assert payload['reviewScope'] == {'numeric': 'quantitative_only', 'facts': 'facts_and_quantitative', 'business': 'business_and_quantitative'}[scope]
    if scope == 'facts':
        assert payload['toolEvidence'] == context.reply_evidence
    if scope == 'business':
        assert payload['roleCapabilities'] and payload['currentActions'] == []
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        node = job.result['nodeExecution']['nodes'][0]
        assert node['state'] == 'succeeded' and node['attempts'] == 2
        assert 'outputLimited' not in job.result['replyReview']
        assert 'private reasoning' not in json.dumps(job.result)
        usage = (await db.scalars(select(ModelUsage).where(ModelUsage.job_id == job.id).order_by(ModelUsage.created_at))).all()
        assert [row.status for row in usage] == ['failed', 'succeeded']
        assert usage[0].actual_output_tokens == first['max_tokens'] and usage[0].error_code == 'invalid_response'
    # Cache only the validated verdict; another read does not call the provider.
    cached = await review_reply(context, ANSWER, **options)
    assert cached == result and len(calls) == 2
    assert (await setup[3]['employee'].get('/api/v1/work-items')).json()['items'] == []


@pytest.mark.parametrize('mode,expected_calls', [('malformed', 4), ('length', 4), ('filter', 1), ('other_finish', 4), ('malformed_after_length', 4)])
async def test_review_errors_keep_strict_validation_classification_and_original_attempt_limit(setup, fast_nodes, monkeypatch, mode, expected_calls):
    context, original, preserved = await configure(setup, monkeypatch)
    calls = []
    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        if mode == 'length' or mode == 'malformed_after_length' and len(calls) == 1:
            return response_for(body, '{"issues":[]}', 'length')
        if mode == 'filter':
            return response_for(body, '{"issues":[]}', 'content_filter')
        if mode == 'other_finish':
            return response_for(body, '{"issues":[]}', 'unknown')
        return response_for(body, '{"issues":[')
    client_for(monkeypatch, respond)
    result = await review_reply(context, ANSWER, business=False, quantitative={'kind': 'quantitative_consistency'})
    assert not result.verified and result.text == '' and result.preview_state == 'withdrawn'
    assert len(calls) == context.calls == expected_calls and original == preserved
    assert all(call['max_tokens'] == 2000 for call in calls)
    assert [call['enable_thinking'] for call in calls] == ([True] + [False] * (expected_calls - 1) if mode in ('length', 'malformed_after_length') else [True] * expected_calls)
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        node = job.result['nodeExecution']['nodes'][0]
        assert node['state'] == 'failed' and node['attempts'] == expected_calls and 'output' not in node
        assert node['errorCode'] == ('content_filter' if mode == 'filter' else 'invalid_response')
        assert 'verdict' not in job.result.get('replyReview', {})


async def test_output_limit_profile_survives_review_reentry_but_not_a_changed_answer(setup, monkeypatch):
    context, _, _ = await configure(setup, monkeypatch, retry=False)
    calls = []
    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        return response_for(body, '', 'length')
    client_for(monkeypatch, respond)
    options = {'business': False, 'quantitative': {'kind': 'quantitative_consistency'}}
    for answer in (ANSWER, ANSWER, ANSWER + '\n请继续核对。'):
        result = await review_reply(context, answer, **options)
        assert not result.verified
    assert [call['enable_thinking'] for call in calls] == [True, False, True]


async def test_output_limit_does_not_invent_unknown_gateway_parameters(setup, fast_nodes, monkeypatch):
    context, original, preserved = await configure(setup, monkeypatch, base='https://unknown.example/v1')
    calls = []
    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        return response_for(body, '{"issues":[]}', 'length' if len(calls) == 1 else 'stop')
    client_for(monkeypatch, respond)
    result = await review_reply(context, ANSWER, business=False, quantitative={'kind': 'quantitative_consistency'})
    assert result.verified and len(calls) == 2 and calls[0] == calls[1]
    assert original == preserved and calls[1]['reasoning_effort'] == 'high'
