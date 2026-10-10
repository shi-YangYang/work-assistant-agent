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
    ('12-5=7', True),
    ('结果：8 / 2 = 4。', True),
    ('库存总共80件。\n甲需要50件。\n乙需要40件。', True),
    ('改版完成1/4，其它样式按10px间距。\n\n（约90字，虚构示例。）', False),
    ('本周（10-05起）没有日报待办，应报0人、已报0人。\n\n最近7天（10-02～10-08）未查到报告。', False),
    ('第2点，也就是异常处理。\n\n第1点属于请求，第3点属于结果，第2点要区分不同分支。', False),
    ('报告1已归档。\n\n报告2已提交。\n\n剩余报告3待整理。', False),
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
async def test_numeric_answer_does_not_trigger_post_generation_judge(setup, raw_first):
    answer = '总共有80件，甲需要50件，乙需要40件，还差10件。'
    fake = NumericModel(model='controlled', api_key='unused', raw_first=raw_first, answer=answer)
    result, stored = await run(setup, fake, '库存80件，甲需要50件，乙需要40件，够不够？不要修改工作。')
    assert result['reply'] == answer and result['job']['taskOutcome']['state'] == 'completed'
    assert fake.calls == 1 and not fake.reviews and fake.repairs == 0
    assert not stored.get('deliveryRepairs')
    assert not result['actions'] and not result['drafts']
    assert (await setup[3]['employee'].get('/api/v1/work-items')).json()['items'] == []


async def test_numeric_content_cannot_hide_missing_business_execution(setup):
    answer = '共100页，已读35页，剩余65页。'
    context, _ = await runtime(setup, '请保存阅读进度')
    await set_delivery(context, answer, business=True)
    fake = NumericModel(model='controlled', api_key='unused', answer=answer)
    result = await assess(context, answer, model=fake)
    assert result.needs_action and result.execution_claims and not result.text
    assert not fake.reviews


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
        assert max_tokens is None
        assert config['parameters']['enable_thinking'] is True
        assert config['parameters']['reasoning_effort'] == 'high'
        await on_event('started')
        return {'choices': [{'message': {'role': 'assistant', 'content': '{"issues":[]}'}, 'finish_reason': 'stop'}]}
    monkeypatch.setattr('app.integrations.models.chat.chat', chat)
    options = {'quantitative': {'kind': 'quantitative_consistency'}, 'business': False}
    first = await review_reply(context, answer, **options)
    second = await review_reply(context, answer, **options)
    assert first.verified and second.verified and first.text == second.text == answer
    assert len(calls) == 1 and original == preserved
