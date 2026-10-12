"""Shared controlled fixtures extracted from test_assistant_execution."""
import json
from langchain_core.messages import AIMessage, ToolMessage
from _support.agent.business_actions import Judge


class ReceiptJudge(Judge):
    def __init__(self, *, receipt=True, allowed=True, required_fields=(), requested_changes=()):
        super().__init__(allowed)
        self.receipt = receipt
        self.required_fields = required_fields
        self.requested_changes = requested_changes

    async def ainvoke(self, messages):
        response = await super().ainvoke(messages)
        verdict = json.loads(response.content)
        if 'allowed' in verdict:
            verdict['receiptOnly'] = self.receipt
            verdict['requiredFields'] = list(self.required_fields)
            verdict['requestedChanges'] = list(self.requested_changes)
        return AIMessage(content=json.dumps(verdict))


def returned(receipt, *, extra=False):
    calls = [{'name': 'execute_business_action', 'id': 'save', 'args': {}}]
    if extra:
        calls.append({'name': 'find_work_items', 'id': 'query', 'args': {'query': ''}})
    return [AIMessage(content='', tool_calls=calls), ToolMessage(name='execute_business_action', tool_call_id='save', content=json.dumps(receipt))]
