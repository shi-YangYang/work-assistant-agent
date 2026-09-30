"""Factual verification stays evidence-focused and uses a bounded reasoning call."""
import json
from copy import deepcopy

import pytest
from app.agent.completion.reply_review import review_reply
from fakes import set_delivery
from test_business_actions import runtime

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('quantitative', [None, {'kind': 'quantitative_consistency'}])
async def test_fact_review_uses_evidence_only_reasoning_and_reuses_cached_verdict(setup, monkeypatch, quantitative):
    context, _ = await runtime(setup, '请核验：建议是否等于必要条件？')
    answer = '建议不代表每次都必须如此，应保留原文适用条件。'
    await set_delivery(context, answer)
    context.delivery = {**context.delivery, 'verification_requested': True, 'verification_quote': '请核验：建议是否等于必要条件？'}
    context.reply_evidence = [{'id': 1, 'tool': 'web_fetch', 'result': 'For this branch, it is recommended.'}]
    original = {'baseUrl': 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'model': 'deepseek-v4.1-flash',
                'streaming': False, 'parameters': {'enable_thinking': True, 'reasoning_effort': 'high'}}
    preserved = deepcopy(original)
    async def resolve(*args):
        return original, 'unused'
    monkeypatch.setattr('app.modules.model_services.bindings.resolve_bound', resolve)
    calls = []
    async def chat(settings, config, key, messages, *, on_event, max_tokens, **kwargs):
        payload = json.loads(messages[-1]['content'])
        calls.append(payload)
        assert max_tokens == 4000
        assert config['parameters']['enable_thinking'] is True
        assert config['parameters']['reasoning_effort'] == 'low'
        assert payload['reviewScope'] == ('facts_and_quantitative' if quantitative else 'facts_only')
        assert payload['verificationQuote'] == context.delivery['verification_quote']
        assert payload['toolEvidence'] == context.reply_evidence
        assert not {'currentActions', 'roleCapabilities', 'conversationTask', 'drafts'} & payload.keys()
        await on_event('started')
        return {'choices': [{'message': {'role': 'assistant', 'content': '{"issues":[]}'}, 'finish_reason': 'stop'}]}
    monkeypatch.setattr('app.integrations.models.chat.chat', chat)
    options = {'business': False, 'quantitative': quantitative}
    first = await review_reply(context, answer, **options)
    second = await review_reply(context, answer, **options)
    assert first.verified and second.verified and first.text == second.text == answer
    assert len(calls) == 1 and original == preserved


async def test_fact_review_protocol_retry_does_not_invite_business_actions(setup):
    from langchain_core.messages import AIMessage
    from app.tasks.nodes.node_execution import initialize
    context, _ = await runtime(setup, '核验文中的建议是否必需')
    context.node_retry = True
    await initialize(context, 'fact-review-protocol')
    answer = '这是建议，不能直接推为必要条件。'
    await set_delivery(context, answer)
    context.delivery = {**context.delivery, 'verification_requested': True, 'verification_quote': '核验文中的建议是否必需'}
    class Judge:
        calls = 0
        async def ainvoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content='{"issues":[{"kind":"missing_action","reason":"创建工作"}]}')
            assert '只允许 fact/missing_response' in messages[-1].content
            assert '不改变本次核对范围' in messages[-1].content
            return AIMessage(content='{"issues":[]}')
    judge = Judge()
    result = await review_reply(context, answer, model=judge, business=False)
    assert judge.calls == 2 and result.verified and result.text == answer
    assert not result.needs_action
