"""Controlled model responses used only by tests, through the real harness/tool loop."""
import json
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI
from pydantic import Field


class ControlledModel(ChatOpenAI):
    scenario: str = 'progress'
    seen_tools: list = Field(default_factory=list, exclude=True)
    seen_images: list = Field(default_factory=list, exclude=True)
    summaries: list = Field(default_factory=list, exclude=True)

    def bind_tools(self, tools, **kwargs):
        self.seen_tools.extend(t.name if hasattr(t, 'name') else t.get('name') for t in tools)
        return super().bind_tools(tools, **kwargs)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        last = messages[-1]
        if any('Context Extraction Assistant' in str(m.content) for m in messages):
            self.summaries.append(True)
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content='员工先前讨论方案，正式进展以工作数据库为准。'))])
        for message in messages:
            if isinstance(message.content, list):
                self.seen_images.extend(b for b in message.content if isinstance(b, dict) and b.get('type') == 'image_url')
        def call(name, args):
            return AIMessage(content='', tool_calls=[{'id': 'controlled-' + name, 'name': name, 'args': args}])
        if self.scenario in ('report', 'report_source'):
            if self.scenario == 'report_source' and not isinstance(last, ToolMessage):
                raw = last.content if isinstance(last.content, str) else '\n'.join(b.get('text', '') for b in last.content if isinstance(b, dict))
                facts = json.loads(raw[raw.index('{'):])['confirmed']
                rows = [r['content'] for r in facts]
                args = {'completed': '\n'.join(r['summary'] for r in rows if r['status'] == 'done'), 'ongoing': '\n'.join(r['summary'] for r in rows if r['status'] != 'done'), 'blockers': '\n'.join(r['blocker'] for r in rows if r['blocker']), 'next': '\n'.join(r['nextStep'] for r in rows if r['nextStep'])}
                return ChatResult(generations=[ChatGeneration(message=call('draft_report', args))])
            reply = AIMessage(content='报告草稿已准备，等待审阅。') if isinstance(last, ToolMessage) else call('draft_report', {'completed': '已完成方案初稿', 'ongoing': '项目继续推进', 'blockers': '等待报价', 'next': '核对报价'})
        elif self.scenario == 'clarify':
            reply = AIMessage(content='这是哪个工作事项的进展？请补充名称。')
        elif isinstance(last, HumanMessage):
            reply = call('find_work_items', {'query': ''})
        elif isinstance(last, ToolMessage) and last.name == 'find_work_items':
            works = json.loads(last.content)
            reply = call('propose_progress', {'title': '受控方案工作', 'summary': '方案初稿已完成' if not works else '已拿到报价，正在核对', 'status': 'in_progress', 'blocker': '等待报价' if not works else '', 'next_step': '核对报价', 'work_id': works[0]['id'] if works else None})
        else:
            reply = AIMessage(content='已整理为进展建议，请确认。')
        return ChatResult(generations=[ChatGeneration(message=reply)])


def controlled_model(scenario='progress'):
    return ControlledModel(model='controlled-test', api_key='test-no-network', base_url='http://127.0.0.1:1', max_retries=0, scenario=scenario)
