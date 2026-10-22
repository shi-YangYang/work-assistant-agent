"""Shared controlled fixtures extracted from test_work_execution_history."""
import json
from langchain_core.messages import AIMessage
from _support.agent.business_actions import Judge


class WorkJudge(Judge):
    def __init__(self, *, preview=False, append=False, allowed=True):
        self.preview, self.append, self.allowed = preview, append, allowed
        super().__init__(allowed)

    async def ainvoke(self, messages):
        verdict = json.loads((await super().ainvoke(messages)).content)
        return AIMessage(content=json.dumps({**verdict,
            'reason': '', 'notRequested': not self.allowed, 'requireConfirmation': self.preview,
            'appendFields': ['summary'] if self.append else [],
            'appendValues': {'summary': '今天完成多次提交'} if self.append else {}}))
