"""Quantitative consistency uses the existing bounded delivery repair path."""
import json

import pytest
from langchain_core.messages import AIMessage
from pydantic import Field

from app.agent.completion.delivery import assess
from app.agent.completion.quantitative_review import quantitative_scope
from app.tasks.models import Job
from test_response_delivery import DeliveryModel, run
from test_business_actions import runtime
from fakes import set_delivery

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('answer,expected', [
    ('这批总共72件，已发送45件，所以还剩27件。', True),
    ('全体40人，其中已签约30人，未签约10人，两部分合计40人。', True),
    ('速度从12提高到18，增加了50%。', True),
    ('The total is 90, including 25 and 65.', True),
    ('1. 收集资料\n2. 讨论总额\n3. 形成结论', False),
    ('2026-09-30 10:30，2026-10-01 11:30，2026-10-02 12:30，共三次。', False),
    ('资料见 https://example.org/total/120/30/90', False),
    ('```python\nprint(120 - 30 == 90)\n```', False),
    ('Python 3.12.1 和产品 2.3.4：两者的总版本号没有数学意义。', False),
    ('你好，先喝口水，我们一起把计划理顺。', False),
])
async def test_numeric_routing_distinguishes_reasoning_from_identifiers(answer, expected):
    assert bool(quantitative_scope(answer)) is expected


class NumericModel(DeliveryModel):
    correction: str = ''
    invalid_quote: str = ''
    issue_reason: str = '相加应等于总量，候选中的组成与总量矛盾。'
    reviews: list = Field(default_factory=list)
    repairs: int = 0

    async def ainvoke(self, messages, *args, **kwargs):
        try:
            payload = json.loads(messages[-1].content)
        except (ValueError, TypeError):
            payload = {}
        if payload.get('task') == 'business_reply_review':
            if payload['reviewScope'] == 'quantitative_only':
                assert 'conversationTask' not in payload and 'currentActions' not in payload
                assert 'kind=fact' in messages[0].content
            self.reviews.append(payload)
            bad = self.invalid_quote and self.invalid_quote in payload['answer']
            return AIMessage(content=json.dumps({'issues': [{'kind': 'fact', 'quote': self.invalid_quote, 'reason': self.issue_reason}] if bad else []}))
        if 'candidate' in payload and 'correction' in payload:
            self.repairs += 1
            return AIMessage(content=self.correction)
        return await super().ainvoke(messages, *args, **kwargs)


@pytest.mark.parametrize('raw_first', [False, True])
async def test_inconsistent_nonfinancial_composition_is_corrected_once_without_business_writes(setup, raw_first):
    wrong = '总共有80件，分给甲50件，分给乙40件，恰好全部分完。'
    correct = '总共有80件，分给甲50件后，只剩30件可给乙；乙若要40件，还差10件。'
    fake = NumericModel(model='controlled', api_key='unused', raw_first=raw_first, answer='按现有库存计算。\n' + wrong, invalid_quote=wrong, correction='按现有库存计算。\n' + correct)
    result, stored = await run(setup, fake, '库存80件，甲需要50件，乙需要40件，够不够？不要修改工作。')
    assert result['reply'] == fake.correction and result['job']['taskOutcome']['state'] == 'completed'
    assert fake.calls == (2 if raw_first else 1) and len(fake.reviews) == 2 and fake.repairs == 1
    assert all(item['reviewScope'] == 'quantitative_only' for item in fake.reviews)
    assert stored['deliveryRepairs'] == (['protocol', 'response'] if raw_first else ['response'])
    assert not result['actions'] and not result['drafts']
    assert (await setup[3]['employee'].get('/api/v1/work-items')).json()['items'] == []


async def test_correct_hypothetical_quantity_answer_is_not_rewritten(setup):
    answer = '如果每箱装12件，5箱就是60件；这是按箱子都装满的假设计算。小算盘拨好了。'
    fake = NumericModel(model='controlled', api_key='unused', answer=answer)
    result, stored = await run(setup, fake, '帮我举个装箱数量的假设例子，不需要查外部资料')
    assert result['reply'] == answer and fake.repairs == 0 and fake.calls == 1
    assert len(fake.reviews) == 1 and not stored.get('deliveryRepairs')


async def test_short_correction_still_rechecked_and_repeated_error_exhausts_original_budget(setup):
    wrong = '两部分合计90件。'
    fake = NumericModel(model='controlled', api_key='unused', answer='总共80件，甲50件、乙30件。' + wrong, invalid_quote=wrong, correction='部分数量以刚才为准。' + wrong)
    result, stored = await run(setup, fake, '核算这组数量')
    assert fake.calls == 1 and fake.repairs == 1 and len(fake.reviews) == 2
    assert fake.reviews[1]['quantitativeConsistency']['continuation']
    assert stored['deliveryRepairs'] == ['response'] and result['job']['taskOutcome']['state'] != 'completed'
    assert wrong not in result['reply'] and '部分数量以刚才为准' in result['reply']


async def test_existing_review_is_shared_and_cached_while_numeric_scope_is_input_bound(setup):
    answer = '共100页，已读35页，剩余65页。'
    context, _ = await runtime(setup, '请核验阅读数量')
    await set_delivery(context, answer, business=True)
    fake = NumericModel(model='controlled', api_key='unused', answer=answer)
    first = await assess(context, answer, model=fake)
    second = await assess(context, answer, model=fake)
    assert first.text == second.text == answer and len(fake.reviews) == 1
    assert fake.reviews[0]['reviewScope'] == 'business_and_quantitative'
    assert first.needs_action  # numeric review cannot claim missing requested business was executed
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        job.result = {**job.result, 'quantitativeReviewInput': 'different-input'}
    await set_delivery(context, '你好，欢迎回来。')
    ordinary = await assess(context, '你好，欢迎回来。', model=fake)
    assert ordinary.text == '你好，欢迎回来。' and len(fake.reviews) == 1


async def test_quantitative_review_uses_bounded_reasoning_and_cache_without_mutating_config(setup, monkeypatch):
    from copy import deepcopy
    from app.agent.completion.reply_review import review_reply
    context, _ = await runtime(setup, '核对数量说明')
    answer = '共80件，取出30件，还剩50件。'
    await set_delivery(context, answer)
    original = {'baseUrl': 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'model': 'deepseek-v4.1-flash',
                'streaming': False, 'parameters': {'enable_thinking': True, 'reasoning_effort': 'high', 'temperature': 0.3}}
    preserved = deepcopy(original)
    async def resolve(*args):
        return original, 'unused'
    monkeypatch.setattr('app.modules.model_services.bindings.resolve_bound', resolve)
    calls = []
    async def chat(settings, config, key, messages, *, on_event, max_tokens, **kwargs):
        calls.append(json.loads(messages[-1]['content']))
        assert max_tokens == 2000
        assert config['parameters']['enable_thinking'] is True
        assert config['parameters']['reasoning_effort'] == 'low'
        await on_event('started')
        return {'choices': [{'message': {'role': 'assistant', 'content': '{"issues":[]}'}, 'finish_reason': 'stop'}]}
    monkeypatch.setattr('app.integrations.models.chat.chat', chat)
    options = {'quantitative': {'kind': 'quantitative_consistency'}, 'business': False}
    first = await review_reply(context, answer, **options)
    second = await review_reply(context, answer, **options)
    assert first.verified and second.verified and first.text == second.text == answer
    assert len(calls) == 1 and original == preserved
