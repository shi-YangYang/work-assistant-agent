"""Job identity regressions through actual PostgreSQL checkpoints and tool execution."""
from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import Field
from sqlalchemy import select

from paa_server.agent.harness import RunContext, ToolBoundary, conversation_history
from paa_server.models import Job, Message, ProgressDraft, Report, now
from paa_server.worker import claim, process_job
from test_company import send

pytestmark = pytest.mark.asyncio


class RecoveryModel(ChatOpenAI):
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


@pytest.mark.parametrize('kind', ['message', 'report'])
async def test_retry_only_resumes_its_job_after_a_later_job_fails(setup, monkeypatch, kind):
    settings, sessions, users, clients = setup
    actor, employee = users['employee'], clients['employee']
    if kind == 'message':
        first = await send(employee, '只有 A 的原始事项')
        first_id = first['jobId']
    else:
        async with sessions.begin() as db:
            report = Report(company_id=actor.company_id, owner_id=actor.id, kind='daily', period='2026-09-12', period_end='2026-09-12', timezone='Asia/Shanghai')
            db.add(report)
            await db.flush()
            report_id = report.id
            a = Job(company_id=actor.company_id, owner_id=actor.id, kind='report', target_id=report.id, base_revision=1)
            db.add(a)
            await db.flush()
            first_id = a.id
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        first_job = await claim(sessions, actor.id)
        assert first_job.id == first_id
        await process_job(first_job, sessions, settings, saver, model=model('仅属于 A', kind, fail_once=True))
        if kind == 'message':
            second = await send(employee, '只有 B 的原始事项')
            second_id = second['jobId']
        else:
            async with sessions.begin() as db:
                b = Job(company_id=actor.company_id, owner_id=actor.id, kind='report', target_id=report_id, base_revision=1)
                db.add(b)
                await db.flush()
                second_id = b.id
        original = ToolBoundary.awrap_tool_call
        blocked = {second_id}

        async def fail_before_b_tool(self, request, handler):
            if request.runtime.context.job_id in blocked:
                blocked.remove(request.runtime.context.job_id)
                raise RuntimeError('Controlled failure before B tool')
            return await original(self, request, handler)

        monkeypatch.setattr(ToolBoundary, 'awrap_tool_call', fail_before_b_tool)
        second_job = await claim(sessions, actor.id)
        assert second_job.id == second_id
        await process_job(second_job, sessions, settings, saver, model=model('仅属于 B', kind))
        assert (await employee.post(f'/api/v1/jobs/{first_id}/retry', json={})).status_code == 200
        retried_a = await claim(sessions, actor.id)
        retry_model = model('仅属于 A', kind)
        await process_job(retried_a, sessions, settings, saver, model=retry_model)
        async with sessions() as db:
            assert (await db.get(Job, first_id)).state == 'succeeded'
            assert (await db.get(Job, second_id)).state == 'failed'
            if kind == 'message':
                drafts = (await db.scalars(select(ProgressDraft).where(ProgressDraft.owner_id == actor.id))).all()
                assert [(draft.message_id, draft.content['title']) for draft in drafts] == [(first['messageId'], '仅属于 A')]
                assert '只有 B' not in str(retry_model.seen)
            else:
                assert (await db.get(Report, report_id)).content['completed'] == '仅属于 A'
        # B must resume its own pending tool, without rerunning the model that
        # proposed it. A different model label would expose an accidental restart.
        assert (await employee.post(f'/api/v1/jobs/{second_id}/retry', json={})).status_code == 200
        retried_b = await claim(sessions, actor.id)
        resumed_model = model('不应重新生成的 C', kind)
        await process_job(retried_b, sessions, settings, saver, model=resumed_model)
        assert resumed_model.calls == 1
        async with sessions() as db:
            assert (await db.get(Job, second_id)).state == 'succeeded'
            if kind == 'message':
                b_draft = await db.scalar(select(ProgressDraft).where(ProgressDraft.message_id == second['messageId']))
                assert b_draft.content['title'] == '仅属于 B'
            else:
                assert (await db.get(Report, report_id)).candidate['content']['completed'] == '仅属于 B'
        # A graph completed before the worker's final DB write reuses its answer.
        async with sessions.begin() as db:
            done = await db.get(Job, first_id)
            done.state, done.fence, done.lease_until = 'running', done.fence + 1, now() + timedelta(seconds=90)
        completed_model = model('不应发生的额外请求', kind)
        await process_job(done, sessions, settings, saver, model=completed_model)
        assert completed_model.calls == 0
        for job_id in (first_id, second_id):
            await saver.adelete_thread(f'{actor.company_id}:{actor.id}:job:{job_id}')


async def test_history_keeps_explicit_clarification_and_excludes_future_or_other_employee(setup):
    settings, sessions, users, clients = setup
    actor = users['employee']
    instant = now()
    async with sessions.begin() as db:
        parent = Message(company_id=actor.company_id, owner_id=actor.id, text='客户是哪一家的？', reply='请补充客户名称。', created_at=instant - timedelta(days=1))
        db.add(parent)
        await db.flush()
        for n in range(15):
            db.add(Message(company_id=actor.company_id, owner_id=actor.id, text='较新的历史消息 ' + str(n), created_at=instant - timedelta(minutes=n + 1)))
        db.add(Message(company_id=actor.company_id, owner_id=users['peer'].id, text='另一个员工的机密', created_at=instant - timedelta(minutes=1)))
    response = await clients['employee'].post('/api/v1/messages', json={'text': '是华远的方案', 'replyTo': parent.id}, headers={'Idempotency-Key': 'history-recovery'})
    assert response.status_code == 202
    job = await claim(sessions, actor.id)
    await send(clients['employee'], '后发的 B 不能成为 A 的历史')
    context = RunContext(actor.id, actor.company_id, job.id, job.fence, sessions, settings)
    content = [{'type': 'text', 'text': '文' * 8000}, *[{'type': 'image_url', 'image_url': {'url': 'controlled-image'}} for _ in range(4)]]
    history = await conversation_history(context, job, content)
    text = str([item.content for item in history])
    assert parent.id in text and '请补充客户名称' in text
    assert '另一个员工的机密' not in text and '后发的 B' not in text
    assert sum(len(item.content) for item in history) <= 20000 - (8000 + 4 * 2048)


class ReferenceRecoveryModel(ChatOpenAI):
    work_id: str
    message_id: str
    new_reference: str | None = None
    calls: int = 0
    tool_results: list[str] = Field(default_factory=list)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        if isinstance(messages[-1], ToolMessage):
            self.tool_results.append(str(messages[-1].content))
        schema = next(t['function']['parameters'] for t in kwargs['tools'] if t['function']['name'] == 'propose_progress')
        assert schema['properties']['status']['enum'] == ['in_progress', 'blocked', 'done']
        assert 'work_id' not in schema['required']
        progress = {'title': '引用纠正后的工作', 'summary': '初稿完成，等待报价', 'status': 'blocked', 'blocker': '等待报价', 'next_step': '收到报价后测算', 'work_id': None}
        new_progress = {k: v for k, v in progress.items() if k != 'work_id'}
        if self.new_reference is not None:
            new_progress['work_id'] = self.new_reference
        actions = [
            ('get_work_item', {'work_id': self.work_id}),
            ('get_message_context', {'message_id': self.message_id}),
            ('propose_progress', {**progress, 'work_id': self.work_id}),
            ('propose_progress', new_progress),
        ]
        if self.calls <= len(actions):
            name, args = actions[self.calls - 1]
            answer = AIMessage(content='', tool_calls=[{'id': f'reference-{self.calls}', 'name': name, 'args': args}])
        else:
            answer = AIMessage(content='进展建议已整理，请确认。')
        return ChatResult(generations=[ChatGeneration(message=answer)])


@pytest.mark.parametrize(('other_owner', 'new_reference'), [('peer', 'null'), ('outsider', None)])
async def test_model_recovers_invalid_references_without_exposing_other_work(setup, other_owner, new_reference):
    from paa_server.models import WorkItem
    settings, sessions, users, clients = setup
    target = users[other_owner]
    async with sessions.begin() as db:
        foreign_work = WorkItem(company_id=target.company_id, owner_id=target.id, title='不可泄露的工作', content={'summary': '不可泄露的内容'})
        foreign_message = Message(company_id=target.company_id, owner_id=target.id, text='不可泄露的消息')
        db.add_all([foreign_work, foreign_message])
        await db.flush()
    sent = await send(clients['employee'])
    job = await claim(sessions, users['employee'].id)
    model = ReferenceRecoveryModel(model='controlled-reference', api_key='no-network', max_retries=0, work_id=foreign_work.id, message_id=foreign_message.id, new_reference=new_reference)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(job, sessions, settings, saver, model=model)
    result = (await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert result['job']['state'] == 'succeeded', result['job']
    assert model.calls == 5
    assert len(model.tool_results) == 4
    assert all('不存在或无权查看' in result for result in model.tool_results[:3])
    assert '不可泄露' not in str(model.tool_results)
    assert len(result['drafts']) == 1 and result['drafts'][0]['workId'] is None
    assert result['drafts'][0]['content']['status'] == 'blocked'
    assert not (await clients['employee'].get('/api/v1/work-items')).json()['items']


async def test_work_search_and_message_context_use_confirmed_state_after_reply(setup):
    import json
    from types import SimpleNamespace
    from paa_server.agent.harness import find_work_items, get_message_context
    from paa_server.models import WorkItem
    settings, sessions, users, clients = setup
    actor = users['employee']
    sent = await send(clients['employee'])
    job = await claim(sessions, actor.id)
    context = RunContext(actor.id, actor.company_id, job.id, job.fence, sessions, settings)
    async with sessions.begin() as db:
        source = await db.get(Message, sent['messageId'])
        source.reply = '尚未确认，只是一条建议'
        work = WorkItem(company_id=actor.company_id, owner_id=actor.id, title='真实联调—海星方案', content={'title':'真实联调—海星方案','summary':'确认后的当前进展','status':'blocked','blocker':'等待报价','nextStep':'收到报价后测算'})
        foreign = WorkItem(company_id=actor.company_id, owner_id=users['peer'].id, title='真实联调—海星方案', content={'summary':'不可泄露'})
        db.add_all([work, foreign])
        await db.flush()
        db.add(ProgressDraft(company_id=actor.company_id, owner_id=actor.id, message_id=source.id, work_id=work.id, content=work.content, status='confirmed', tool_key='confirmed-reference'))
    runtime = SimpleNamespace(context=context)
    results = json.loads(await find_work_items.coroutine(query='真实联调 海星方案', runtime=runtime))
    assert [item['id'] for item in results] == [work.id]
    assert context.read_versions == {work.id: work.revision}
    source = json.loads(await get_message_context.coroutine(message_id=sent['messageId'], runtime=runtime))
    assert source['progress'] == [{'status':'confirmed','workId':work.id}]
    assert source['reply'] == '尚未确认，只是一条建议'
    assert '不可泄露' not in str(results) + str(source)
