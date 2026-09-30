"""Controlled model responses used only by tests, through the real harness/tool loop."""
import json
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI
from pydantic import Field


class ReviewedFixtureModel(ChatOpenAI):
    """Fixed benign fixtures supply a separate review response, not network IO.

    Adversarial review classification is exercised explicitly in action tests.
    Keep this request out of each scenario's graph step/call counters.
    """
    async def ainvoke(self, input, config=None, *, stop=None, **kwargs):
        if isinstance(input, list) and input and isinstance(input[-1], HumanMessage):
            try:
                payload = json.loads(input[-1].content)
            except (ValueError, TypeError):
                payload = {}
            if payload.get('task') == 'business_reply_review':
                return AIMessage(content=json.dumps({'issues': []}))
            if payload.get('proposedOperation'):
                return AIMessage(content=json.dumps({'allowed': True, 'requireConfirmation': payload['proposedOperation']['action'] in ('propose_progress', 'propose_followup'), 'quote': payload['currentUserText'], 'reason': '受控待确认建议；自动执行与语义边界由独立用例验证'}))
            if payload.get('task') == 'report_fact_review':
                return AIMessage(content='{"valid":true}')
        result = await super().ainvoke(input, config, stop=stop, **kwargs)
        # Preserve scenario prose while supplying the current terminal protocol.
        names = {tool.get('function', {}).get('name') for tool in kwargs.get('tools', [])}
        if 'finish_task' in names and not result.tool_calls:
            result = completion(result.text)
        return result


class ControlledModel(ReviewedFixtureModel):
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
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content=json.dumps(args, ensure_ascii=False)))])
            reply = AIMessage(content=json.dumps({'completed': '已完成方案初稿', 'ongoing': '项目继续推进', 'blockers': '等待报价', 'next': '核对报价'}, ensure_ascii=False))
        elif self.scenario == 'clarify':
            reply = AIMessage(content='这是哪个工作事项的进展？请补充名称。')
        elif isinstance(last, HumanMessage):
            reply = call('find_work_items', {'query': ''})
        elif isinstance(last, ToolMessage) and last.name == 'find_work_items':
            works = json.loads(last.content)['items']
            reply = call('propose_progress', {'title': '受控方案工作', 'summary': '方案初稿已完成' if not works else '已拿到报价，正在核对', 'status': 'in_progress', 'blocker': '等待报价' if not works else '', 'next_step': '核对报价', 'work_id': works[0]['id'] if works else None})
        else:
            reply = AIMessage(content='已整理为进展建议，请确认。')
        return ChatResult(generations=[ChatGeneration(message=reply)])


def controlled_model(scenario='progress'):
    return ControlledModel(model='controlled-test', api_key='test-no-network', base_url='http://127.0.0.1:1', max_retries=0, scenario=scenario)


def completion(answer, *, task=None, business=False, **extra):
    return AIMessage(content='', tool_calls=[{'name': 'finish_task', 'id': 'fixture-completion',
        'args': {'answer': answer, 'task': task or {'state': 'completed'}, 'business_requested': business, 'verification_requested': False, **extra}}])


async def set_delivery(context, answer, *, task=None, business=False):
    from app.modules.messages.models import Message
    from app.modules.operations.receipts import message_actions
    from app.tasks.lease import lease
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        message = await db.get(Message, job.target_id)
        cards = await message_actions(db, actor, message)
    context.delivery = {'version': 1, 'answer': answer, 'task': task or {'state': 'completed'},
        'business_requested': business, 'verification_requested': False,
        'operation_ids': [card['id'] for card in cards], 'response_complete': True, 'response_issue': ''}


def wire_completion(answer, *, task=None, business=False, **extra):
    call = completion(answer, task=task, business=business, **extra).tool_calls[0]
    return {'role': 'assistant', 'content': '', 'tool_calls': [{'type': 'function', 'id': call['id'],
        'function': {'name': call['name'], 'arguments': json.dumps(call['args'], ensure_ascii=False)}}]}
