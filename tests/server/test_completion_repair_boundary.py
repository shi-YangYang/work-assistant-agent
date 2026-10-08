"""Internal completion repairs keep the original request as the user-facing task."""
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from app.agent.completion.delivery import PUBLIC_REPLY_POLICY
from fakes import completion
from test_response_delivery import DeliveryModel, run

pytestmark = pytest.mark.asyncio


class MislabelledReadModel(DeliveryModel):
    repairs: list = Field(default_factory=list)

    async def ainvoke(self, input, config=None, *, stop=None, **kwargs):
        if isinstance(input, list) and isinstance(input[-1], HumanMessage):
            try:
                payload = json.loads(input[-1].content)
            except (ValueError, TypeError):
                payload = {}
            if payload.get('task') == 'business_reply_review':
                assert payload['currentUserText'] == '整理三条注意事项，不要保存报告。'
                return AIMessage(content='{"issues":[]}')
        return await super().ainvoke(input, config, stop=stop, **kwargs)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        assert any(PUBLIC_REPLY_POLICY in message.content for message in messages if isinstance(message, SystemMessage))
        if self.calls == 1:
            result = completion(self.answer)
            result.tool_calls[0]['args']['business_requested'] = True
        elif self.calls == 2:
            instruction = messages[-1]
            assert instruction.id.startswith('completion-repair:')
            assert '原用户请求还有遗漏的操作' not in instruction.content
            assert '无业务回执是正常的' in instruction.content
            assert '不汇报本次内部纠错' in instruction.content
            self.repairs.append(instruction.content)
            result = AIMessage(content='', tool_calls=[{
                'name': 'get_business_actions', 'id': 'inspect-existing-receipts', 'args': {},
            }])
        else:
            assert self.calls == 3
            assert isinstance(messages[-1], ToolMessage)
            assert messages[-1].name == 'get_business_actions'
            assert json.loads(messages[-1].content) == []
            result = completion(self.answer)
        return ChatResult(generations=[ChatGeneration(message=result)])


async def test_false_business_flag_repairs_metadata_without_creating_work_or_reporting_control_messages(setup):
    answer = '注意范围、来源和时效。\n\n[参考文档](https://example.org/guide)'
    fake = MislabelledReadModel(model='controlled', api_key='unused', answer=answer)
    result, stored = await run(setup, fake, '整理三条注意事项，不要保存报告。')
    assert result['reply'] == answer and result['job']['taskOutcome']['state'] == 'completed'
    assert not result['actions'] and not result['interactions']
    assert stored['deliveryRepairs'] == ['action'] and len(fake.repairs) == 1
    assert not stored['incompleteTask'] and fake.calls == 3
    assert (await setup[3]['employee'].get('/api/v1/work-items')).json()['items'] == []
