"""Shared controlled fixtures extracted from test_response_delivery."""
import json
from pydantic import Field
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from _support.agent.fakes import ReviewedFixtureModel, completion
from app.tasks.processing.handlers import process_job
from app.tasks.runtime.queue import claim
from app.tasks.models import Job


class DeliveryModel(ReviewedFixtureModel):
    answer: str = '这是完整答复。'
    calls: int = 0
    raw_first: bool = False
    invalid: bool = False
    mixed: bool = False
    repeat_invalid_protocol: bool = False
    verification_requested: bool = False
    verification_quote: str = ''
    task: dict = Field(default_factory=lambda: {'state': 'completed'})
    requests: list = Field(default_factory=list)
    async def ainvoke(self, input, config=None, *, stop=None, **kwargs):
        # This fixture deliberately exercises raw protocol replies as well.
        return await super(ReviewedFixtureModel, self).ainvoke(input, config, stop=stop, **kwargs)
    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        self.requests.append({'tools': [tool['function']['name'] for tool in kwargs.get('tools', [])], 'tool_choice': kwargs.get('tool_choice')})
        recovering = any(isinstance(message, HumanMessage) and (message.id or '').startswith('delivery-repair:') for message in messages)
        if self.invalid or self.raw_first and self.calls == 1 or recovering and not self.repeat_invalid_protocol:
            result = AIMessage(content=self.answer)
        else:
            result = completion(self.answer, task=self.task, verification_requested=self.verification_requested, verification_quote=self.verification_quote)
        if self.mixed and self.calls == 1:
            result.tool_calls.append({'type': 'tool_call', 'name': 'execute_business_action', 'id': 'mixed-write', 'args': {'step': 1, 'action': 'create_work', 'changes': {'title': '不该执行'}}})
        return ChatResult(generations=[ChatGeneration(message=result)])


def model(**kwargs):
    return DeliveryModel(model='controlled', api_key='controlled', **kwargs)


async def run(setup, fake, text='帮我分析一下', **payload):
    settings, sessions, users, clients = setup
    from _support.http.company import keyed
    response = await clients['employee'].post('/api/v1/messages', json={'text': text, **payload}, headers=keyed())
    assert response.status_code == 202, response.text
    sent = response.json()
    job = await claim(sessions, users['employee'].id)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(job, sessions, settings, saver, model=fake)
    result = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    async with sessions() as db:
        saved = await db.get(Job, job.id)
        return result, saved.result


class RoutingModel(DeliveryModel):
    reviews: int = 0
    async def ainvoke(self, messages, *args, **kwargs):
        try:
            payload = json.loads(messages[-1].content)
        except (ValueError, TypeError):
            payload = {}
        if payload.get('task') == 'business_reply_review':
            self.reviews += 1
            return AIMessage(content='{"issues":[]}')
        return await super().ainvoke(messages, *args, **kwargs)


class PageDeliveryModel(RoutingModel):
    async def _agenerate(self, messages, *args, **kwargs):
        if not self.calls:
            self.calls += 1
            reply = AIMessage(content='', tool_calls=[{'name': 'web_fetch', 'id': 'reference', 'args': {'url': 'https://example.org/reference'}}])
            return ChatResult(generations=[ChatGeneration(message=reply)])
        return await super()._agenerate(messages, *args, **kwargs)
