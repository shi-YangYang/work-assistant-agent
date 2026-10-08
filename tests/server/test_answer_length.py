"""Explicit response lengths use local counting and the existing repair budget."""
import json
import pytest
from langchain_core.messages import AIMessage
from pydantic import Field
from app.agent.completion.answer_length import AnswerLength, bounds, check_length
from test_response_delivery import DeliveryModel, run

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('quote,unit,expected', [
    ('约1000字', 'cjk_characters', (800, 1200)),
    ('100字以内', 'cjk_characters', (0, 100)),
    ('至少300字', 'cjk_characters', (300, None)),
    ('200 words', 'words', (160, 240)),
    ('1000字', 'cjk_characters', (800, 1200)),
    ('精确100字', 'cjk_characters', (100, 100)),
    ('exactly 200 words', 'words', (200, 200)),
    ('exactly 200 English words', 'words', (200, 200)),
    ('英文200词', 'words', (160, 240)),
    ('200个英文单词', 'words', (160, 240)),
    ('under 120 words', 'words', (0, 119)),
    ('150 to 200 words', 'words', (150, 200)),
])
async def test_length_bounds_are_derived_from_exact_source(quote, unit, expected):
    requirement = AnswerLength(quote=quote, unit=unit, body='正文')
    assert bounds(requirement, '请写 ' + quote + '。') == expected


@pytest.mark.parametrize('quote,unit,body,answer,user_text', [
    ('200 words', 'words', 'a', 'a', 'Write 1200 words.'),
    ('100字', 'cjk_characters', '文', '文', '约100字'),
    ('100字', 'cjk_characters', '文', '文', '100字以内'),
    ('100字', 'words', 'a', 'a', '100字'),
    ('10字以内', 'cjk_characters', '文', '另一段', '10字以内'),
    ('10字以内', 'cjk_characters', '文', '文' + '另' * 100, '10字以内'),
    ('10字以内', 'cjk_characters', '文', '另' * 100 + '文', '10字以内'),
    ('100-50 words', 'words', 'a', 'a', '100-50 words'),
    ('200 English words', 'words', 'a', 'a', 'exactly 200 English words'),
    ('200词', 'words', 'a', 'a', '精确英文200词'),
    ('英文200字', 'cjk_characters', '文', '文', '英文200字'),
])
async def test_length_contract_cannot_forge_source_unit_or_partial_body(quote, unit, body, answer, user_text):
    assert check_length(AnswerLength(quote=quote, unit=unit, body=body), answer, user_text)


@pytest.mark.parametrize('count,valid', [(799, False), (800, True), (1200, True), (1201, False)])
async def test_chinese_approximation_boundaries_exclude_title_punctuation(count, valid):
    body = '雨' * count + '，。'
    requirement = AnswerLength(quote='约1000字', unit='cjk_characters', body=body)
    assert bool(check_length(requirement, '# 雨\n\n' + body, '写约1000字。')) is not valid


class LengthModel(DeliveryModel):
    length: dict = Field(default_factory=dict)
    correction: str = ''
    repairs: int = 0

    async def _agenerate(self, messages, *args, **kwargs):
        result = await super()._agenerate(messages, *args, **kwargs)
        result.generations[0].message.tool_calls[0]['args']['answer_length'] = self.length
        return result

    async def ainvoke(self, messages, *args, **kwargs):
        try:
            payload = json.loads(messages[-1].content)
        except (ValueError, TypeError):
            payload = {}
        if 'candidate' in payload and 'correction' in payload:
            self.repairs += 1
            assert payload['lengthRequirement'] == self.length
            return AIMessage(content=self.correction)
        assert payload.get('task') != 'business_reply_review'
        return await super().ainvoke(messages, *args, **kwargs)


class ReferenceLengthModel(LengthModel):
    async def _agenerate(self, messages, *args, **kwargs):
        result = await super()._agenerate(messages, *args, **kwargs)
        result.generations[0].message.tool_calls[0]['args']['answer_length'] = {
            **self.length, 'quote': '150 words' if self.calls == 1 else self.length['quote']}
        return result


async def test_invalid_length_source_uses_bounded_protocol_repair_before_counting(setup):
    body = 'rain ' * 200
    fake = ReferenceLengthModel(model='controlled', api_key='unused', answer=body,
                                length={'quote': '200 words', 'unit': 'words', 'body': body})
    result, stored = await run(setup, fake, 'Write 200 words.')
    assert result['job']['taskOutcome']['state'] == 'completed' and fake.calls == 2
    assert fake.repairs == 0 and stored['deliveryRepairs'] == ['protocol']


@pytest.mark.parametrize('unit,quote,before,after,valid', [
    ('cjk_characters', '约1000字', '雨' * 700, '雨' * 1000, True),
    ('words', '200 words', 'rain ' * 50, 'rain ' * 200, True),
    ('cjk_characters', '120字以内', '雨' * 160, '雨' * 100, True),
    ('words', '200 words', 'rain ' * 50, 'rain ' * 80, False),
])
async def test_count_failure_repairs_once_and_rechecks_without_extra_judge(setup, unit, quote, before, after, valid):
    prefix = '# 雨\n\n'
    fake = LengthModel(model='controlled', api_key='unused', answer=prefix + before,
                       correction=prefix + after, length={'quote': quote, 'unit': unit, 'body': before})
    result, stored = await run(setup, fake, '写 ' + quote + '，不要保存。')
    assert fake.calls == 1 and fake.repairs == 1
    assert stored['deliveryRepairs'] == ['response']
    assert not any(node['kind'] == 'review' for node in result['job']['nodes'])
    assert (result['job']['taskOutcome']['state'] == 'completed') is valid
    assert not result['actions'] and not result['drafts']
    if valid:
        assert result['reply'] == prefix + after
