"""Shared controlled fixtures extracted from test_work_change_plan."""
import json
from langchain_core.messages import AIMessage
from app.agent.actions.work_change_plan import FIELDS, WorkChangePlan, compact_plan


class PlanJudge:
    def __init__(self, fields):
        self.fields, self.inputs = fields, []

    async def ainvoke(self, messages):
        payload = next(json.loads(message.content) for message in messages if str(message.content).startswith('{'))
        self.inputs.append(payload)
        assert 'proposedOperation' not in payload and 'changes' not in payload
        result = {field: {'mode': 'preserve', 'quotes': [], 'value': None} for field in FIELDS}
        for field, (mode, quote, value) in self.fields.items():
            result[field] = {'mode': mode, 'quotes': [{'messageId': payload['messageId'], 'text': quote}], 'value': value}
        return AIMessage(content=json.dumps(compact_plan(WorkChangePlan.model_validate(result))))
