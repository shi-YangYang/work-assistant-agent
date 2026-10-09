"""Memory saves through the worker, graph, middleware and real database."""
import json
import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field
from test_assistant_memory import PATH
from test_response_delivery import DeliveryModel, run

pytestmark = pytest.mark.asyncio


class MemoryModel(DeliveryModel):
    preference: str = '喜欢吃米饭。'
    evidence: str = '我喜欢吃米饭'
    receipts: list = Field(default_factory=list)
    repeat_count: int = 1

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        names = {tool['function']['name'] for tool in kwargs.get('tools', [])}
        prior = [message for message in messages if isinstance(message, ToolMessage)]
        self.receipts = [json.loads(message.content) for message in prior if message.name == 'save_memory']
        if not any(message.name == 'load_tools' for message in prior):
            call = {'name': 'load_tools', 'args': {'groups': ['memory']}, 'id': 'load-memory'}
        elif len(self.receipts) < self.repeat_count:
            call = {'name': 'save_memory', 'id': f'save-{len(self.receipts)}',
                    'args': {'new_text': self.preference, 'evidence': self.evidence}}
        else:
            call = None
        if call:
            assert call['name'] in names
            answer = AIMessage(content='', tool_calls=[call])
        else:
            answer = AIMessage(content='记住啦。')
        return ChatResult(generations=[ChatGeneration(message=answer)])


@pytest.mark.parametrize(('text', 'preference'), [('我喜欢吃米饭', '喜欢吃米饭。'), ('我喜欢睡觉', '- 喜欢睡觉。')])
async def test_save_success_reaches_model_without_another_save(setup, text, preference):
    fake = MemoryModel(model='controlled', api_key='no-network', evidence=text, preference=preference)
    result, stored = await run(setup, fake, text)
    assert result['reply'] == '记住啦。', result
    assert len(fake.receipts) == 1 and fake.receipts[0]['state'] == 'succeeded', fake.receipts
    assert fake.calls == 3
    assert (await setup[3]['employee'].get(PATH)).json()['markdown'] == preference
    assert len(stored['memoryOperations']) == 1
