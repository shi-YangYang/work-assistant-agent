"""Shared controlled fixtures extracted from test_assistant_write_scope."""
import json
from langchain_core.messages import AIMessage


class ScopeJudge:
    def __init__(self, requested, preview=False): self.requested, self.preview = requested, preview
    async def ainvoke(self, messages):
        payload = json.loads(messages[-1].content)
        return AIMessage(content=json.dumps({'allowed': self.requested, 'requireConfirmation': self.preview, 'quote': payload['currentUserText'], 'reason': '仅讨论，不保存' if not self.requested else '', 'notRequested': not self.requested}))
