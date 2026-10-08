"""Historical length metadata is readable but cannot add online model work."""
import pytest
from pydantic import Field
from app.agent.completion.delivery import Delivery
from test_response_delivery import DeliveryModel, run

pytestmark = pytest.mark.asyncio


class LengthModel(DeliveryModel):
    length: dict = Field(default_factory=dict)

    async def _agenerate(self, messages, *args, **kwargs):
        result = await super()._agenerate(messages, *args, **kwargs)
        result.generations[0].message.tool_calls[0]['args']['answer_length'] = self.length
        return result


@pytest.mark.parametrize('length', [
    {'quote': '1000字', 'unit': 'cjk_characters'},
    {'quote': '不属于当前请求的旧声明', 'unit': 'words', 'body': '另一份正文'},
    {'quote': '精确3字', 'unit': 'cjk_characters', 'exclude_title': True},
])
async def test_legacy_length_metadata_never_counts_or_requests_rewrite(setup, monkeypatch, length):
    async def forbidden(*args, **kwargs):
        pytest.fail('Legacy length metadata must not trigger a model rewrite')
    monkeypatch.setattr('app.agent.completion.response_repair.repair_response', forbidden)
    fake = LengthModel(model='controlled', api_key='unused', answer='完整交付的测试正文。', length=length)
    result, stored = await run(setup, fake, '写一篇1000字作文')
    assert result['reply'] == fake.answer and fake.calls == 1
    assert result['job']['taskOutcome']['state'] == 'completed'
    assert not stored.get('deliveryRepairs')
    assert not result['actions'] and not result['drafts']


async def test_length_fields_are_compatibility_only_not_provider_schema():
    from app.agent.tools.completion import finish_task
    from app.agent.prompts.main import main_policy
    schema = finish_task.tool_call_schema.model_json_schema()
    assert 'answer_length' not in schema['properties']
    assert 'AnswerLength' not in schema.get('$defs', {})
    assert 'answer_length' not in Delivery.model_json_schema()['properties']
    for role in ('employee', 'admin'):
        policy = main_policy(role)
        assert '{"length"' not in policy and '程序计数' not in policy
    stored = Delivery(answer='正文', task={'state': 'completed'}, business_requested=False,
                      verification_requested=False, answer_length={
                          'quote': '1000字', 'unit': 'cjk_characters', 'body': '旧正文'})
    assert Delivery.model_validate_json(stored.model_dump_json()).answer_length.body == '旧正文'
