"""Shared controlled fixtures extracted from test_tool_catalog."""
import json
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field
from _support.agent.response_delivery import DeliveryModel


class CatalogModel(DeliveryModel):
    scenario: str = 'query'
    receipt_only: bool = False
    authorizations: list = Field(default_factory=list)
    schemas: list = Field(default_factory=list)
    systems: list = Field(default_factory=list)

    async def ainvoke(self, input, config=None, *, stop=None, **kwargs):
        if isinstance(input, list) and input and isinstance(input[-1], HumanMessage):
            try:
                payload = json.loads(input[-1].content)
            except (ValueError, TypeError):
                payload = {}
            if payload.get('proposedOperation'):
                self.authorizations.append(payload)
                return AIMessage(content=json.dumps({'allowed': True, 'quote': payload['currentUserText'], 'reason': '', 'receiptOnly': self.receipt_only}))
        return await super().ainvoke(input, config, stop=stop, **kwargs)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        tools = kwargs.get('tools', [])
        names = [tool['function']['name'] for tool in tools]
        self.requests.append({'tools': names, 'tool_choice': kwargs.get('tool_choice')})
        self.schemas.append(tools)
        self.systems.append(messages[0].text)
        prior = [message for message in messages if isinstance(message, ToolMessage)]

        def call(name, args, identifier):
            assert name in names, (name, names)
            return AIMessage(content='', tool_calls=[{'id': identifier, 'name': name, 'args': args}])

        if self.scenario == 'prose':
            answer = AIMessage(content='<!--noria:{}-->\n' + self.answer)
        elif not any(message.name == 'load_tools' for message in prior):
            groups = ['files'] if self.scenario == 'files' else ['work']
            if self.scenario == 'files' and 'files' not in tools[0]['function']['parameters']['properties']['groups']['items']['enum']:
                groups = ['documents']
            answer = call('load_tools', {'groups': groups}, 'load-capability')
        elif self.scenario == 'query' and not any(message.name == 'find_work_items' for message in prior):
            answer = call('find_work_items', {'query': ''}, 'read-work')
        elif self.scenario == 'create' and not any(message.name == 'execute_business_action' for message in prior):
            answer = call('execute_business_action', {'step': 1, 'action': 'create_work', 'changes': {'title': '目录验证工作'}}, 'write-work')
        else:
            answer = AIMessage(content='<!--noria:{}-->\n' + self.answer)
        return ChatResult(generations=[ChatGeneration(message=answer)])
