"""Shared controlled fixtures extracted from test_recovery."""
from _support.agent.fakes import ReviewedFixtureModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


class RecoveryModel(ReviewedFixtureModel):
    label: str
    kind: str = 'message'
    fail_once: bool = False
    calls: int = 0
    seen: list = Field(default_factory=list)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        self.seen.append([str(message.content) for message in messages])
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError('Controlled model failure before any tool')
        if isinstance(messages[-1], ToolMessage):
            answer = AIMessage(content='本任务的建议已保存。')
        else:
            name = 'propose_progress' if self.kind == 'message' else 'draft_report'
            args = {'title': self.label, 'summary': self.label, 'status': 'in_progress', 'blocker': '', 'next_step': '', 'work_id': None} if self.kind == 'message' else {'completed': self.label, 'ongoing': '', 'blockers': '', 'next': ''}
            answer = AIMessage(content='', tool_calls=[{'id': 'tool-' + self.label, 'name': name, 'args': args}])
        return ChatResult(generations=[ChatGeneration(message=answer)])


def model(label, kind='message', fail_once=False):
    return RecoveryModel(model='controlled-recovery', api_key='no-network', base_url='http://127.0.0.1:1', max_retries=0, label=label, kind=kind, fail_once=fail_once)
