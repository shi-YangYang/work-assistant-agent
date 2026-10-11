"""Shared controlled fixtures extracted from test_memory_tool_flow."""
import json
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field
from _support.agent.response_delivery import DeliveryModel


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
