"""Memory saves through the worker, graph, middleware and real database."""
import json
import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field
from _support.agent.assistant_memory import PATH
from _support.agent.response_delivery import DeliveryModel, run
from _support.agent.memory_tool_flow import MemoryModel

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(('text', 'preference'), [('我喜欢吃米饭', '喜欢吃米饭。'), ('我喜欢睡觉', '- 喜欢睡觉。')])
async def test_save_success_reaches_model_without_another_save(setup, text, preference):
    fake = MemoryModel(model='controlled', api_key='no-network', evidence=text, preference=preference)
    result, stored = await run(setup, fake, text)
    assert result['reply'] == '记住啦。', result
    assert len(fake.receipts) == 1 and fake.receipts[0]['state'] == 'succeeded', fake.receipts
    assert fake.calls == 3
    assert (await setup[3]['employee'].get(PATH)).json()['markdown'] == preference
    assert len(stored['memoryOperations']) == 1
