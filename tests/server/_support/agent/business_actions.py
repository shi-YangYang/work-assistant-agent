"""Shared controlled fixtures extracted from test_business_actions."""
import json
from langchain_core.messages import AIMessage
from app.agent.actions.operations import execute
from app.agent.tools.business.work import get_work_item
from app.tasks.context import RunContext
from app.tasks.models import Job
from app.tasks.runtime.queue import claim
from _support.http.company import keyed, send
from types import SimpleNamespace


class Judge:
    def __init__(self, allowed=True, *, failure_kind='invalid_arguments'):
        self.allowed, self.inputs = allowed, []
        self.failure_kind = failure_kind
    async def ainvoke(self, messages):
        payload = json.loads(messages[-1].content)
        if payload.get('task') == 'report_fact_review':
            return AIMessage(content='{"valid":true}')
        self.inputs.append(payload)
        return AIMessage(content=json.dumps({'allowed': self.allowed, 'quote': payload['currentUserText'], 'reason': '' if self.allowed else '这只是引用或讨论，请明确操作。', 'failureKind': self.failure_kind}))


async def runtime(setup, text='帮我创建工作：报价方案', who='employee', allowed=True):
    settings, sessions, users, clients = setup
    sent = await send(clients[who], text)
    job = await claim(sessions, users[who].id)
    context = RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, settings, source_revision=0, intent_model=Judge(allowed))
    return context, sent


async def finish(context):
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        job.state, job.lease_until = 'succeeded', None


async def read_work(context, identifier):
    return json.loads(await get_work_item.coroutine(identifier, SimpleNamespace(context=context)))


async def create(client, title='报价方案', **extra):
    r = await client.post('/api/v1/work-items', json={'title': title, **extra}, headers=keyed())
    assert r.status_code == 201, r.text
    return r.json()


class ReplyJudge:
    def __init__(self, kinds, *, scopes=None, fail=False, forged_evidence=False):
        self.kinds, self.fail, self.forged_evidence, self.inputs = kinds, fail, forged_evidence, []
        self.scopes = scopes if scopes is not None else ['answer'] * len(kinds)
        assert len(self.scopes) == len(kinds)
    async def ainvoke(self, messages):
        payload = json.loads(messages[-1].content)
        self.inputs.append(payload)
        if self.fail:
            from app.tasks.context import BudgetExceeded
            raise BudgetExceeded('existing call budget exhausted')
        import re
        parts = [piece.strip() for piece in re.split(r'(?<=[。！？!?])|(?<=[.;])(?=\s|$)', payload['answer']) if piece.strip()]
        if len(self.kinds) == 1:
            parts = [payload['answer']]
        issues = []
        for part, kind in zip(parts, self.kinds):
            if kind in ('execution', 'unsupported'):
                issues.append({'kind': 'execution' if kind == 'execution' else 'fact', 'quote': part, 'reason': '受控场景：执行结果不成立'})
        if self.forged_evidence:
            issues.append({'kind': 'fact', 'quote': payload['answer'], 'reason': '伪造依据', 'evidence': [99999]})
        return AIMessage(content=json.dumps({'issues': issues}))


async def run_reply(setup, text, answer, judge, *, read_report=False, before=None):
    from langchain_core.messages import ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_openai import ChatOpenAI
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from app.tasks.processing.handlers import process_job
    class ReplyModel(ChatOpenAI):
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            from _support.agent.fakes import completion
            response = completion(answer, business=bool(before) or 'execution' in getattr(judge, 'kinds', []))
            if read_report and not isinstance(messages[-1], ToolMessage):
                response = AIMessage(content='', tool_calls=[{'id': 'read-report', 'name': 'query_reports', 'args': {}}])
            return ChatResult(generations=[ChatGeneration(message=response)])
    settings, sessions, _, c = setup
    context, sent = await runtime(setup, text)
    if before:
        await before(context)
    async with sessions() as db:
        job = await db.get(Job, context.job_id)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(job, sessions, settings, saver, model=ReplyModel(model='controlled-no-network', api_key='test'), reply_model=judge)
    return (await c['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
