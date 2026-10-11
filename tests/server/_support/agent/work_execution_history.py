"""Shared controlled fixtures extracted from test_work_execution_history."""
import json
from langchain_core.messages import AIMessage


class WorkJudge:
    def __init__(self, *, preview=False, append=False, allowed=True):
        self.preview, self.append, self.allowed = preview, append, allowed
        self.inputs = []

    async def ainvoke(self, messages):
        payload = json.loads(messages[-1].content)
        self.inputs.append(payload)
        return AIMessage(content=json.dumps({'allowed': self.allowed, 'quote': payload['currentUserText'],
            'reason': '', 'notRequested': not self.allowed, 'requireConfirmation': self.preview,
            'appendFields': ['summary'] if self.append else [],
            'appendValues': {'summary': '今天完成多次提交'} if self.append else {}}))
