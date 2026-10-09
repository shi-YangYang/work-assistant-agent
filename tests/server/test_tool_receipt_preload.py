"""Adjacent, revalidated receipts remove discovery only; no paid model IO."""
import json
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import Field
from sqlalchemy import func, select

from app.agent.actions.operations import execute
from app.agent.context.history import conversation_history
from app.agent.harness import invoke_harness
from app.agent.tools import catalog
from app.db.base import now
from app.modules.members.models import Member
from app.modules.messages.models import Message
from app.modules.operations.models import BusinessAction
from app.modules.reports.models import Report
from app.modules.work.models import WorkItem
from app.tasks.models import Job
from fakes import ReviewedFixtureModel
from test_assistant_execution import ReceiptJudge
from test_business_actions import create, finish
from test_documents import running_context
from test_management import conversation, message
from test_work_change_plan import PlanJudge

pytestmark = pytest.mark.asyncio


async def turn(setup, conv, text, who='employee'):
    settings, sessions, users, clients = setup
    sent = await message(clients[who], conv, text)
    context = await running_context(settings, sessions, users[who], sent)
    context.source_revision = 0
    context.intent_model = ReceiptJudge()
    return context, sent


async def groups(context):
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
    history = await conversation_history(context, job, '')
    assert 'toolReceiptIds' not in str(history) and 'previousMessageId' not in str(history)
    return catalog.loaded_groups(context, job)


async def prior_work(setup, conv, title='客户方案'):
    context, sent = await turn(setup, conv, '创建工作：' + title)
    card = await execute(context, step=1, action='create_work', changes={'title': title})
    assert card['state'] == 'succeeded'
    await finish(context)
    return card, sent


class ContinuationModel(ReviewedFixtureModel):
    kind: str
    target: str
    offered: list = Field(default_factory=list)
    reads: list = Field(default_factory=list)

    async def _agenerate(self, messages, **kwargs):
        names = [tool['function']['name'] for tool in kwargs.get('tools', [])]
        self.offered.append(names)
        read = 'get_work_item' if self.kind == 'work' else 'query_reports'
        seen = [item for item in messages if isinstance(item, ToolMessage) and item.name == read]
        if read not in names:
            name, args = 'load_tools', {'groups': [self.kind]}
        elif not seen:
            name = read
            args = {'work_id': self.target} if self.kind == 'work' else {'report_id': self.target}
        else:
            result = json.loads(seen[-1].content)
            item = result if self.kind == 'work' else result['items'][0]
            self.reads.append(item)
            name = 'execute_business_action'
            args = {'step': 1, 'action': 'update_work' if self.kind == 'work' else 'submit_report',
                    'target_id': self.target, 'expected_revision': item['revision']}
            if self.kind == 'work':
                args['changes'] = {'nextStep': '联系客户'}
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content='', tool_calls=[{
            'id': 'call-' + str(len(self.offered)), 'name': name, 'args': args}]))])


@pytest.mark.parametrize('kind', ['work', 'reports'])
@pytest.mark.parametrize('seeded', [False, True])
async def test_continuation_removes_one_loader_round_with_real_reads_and_writes(setup, monkeypatch, kind, seeded):
    settings, sessions, users, clients = setup
    conv = await conversation(clients['employee'])
    if kind == 'work':
        card, _ = await prior_work(setup, conv)
        target = card['objectId']
        # A new version after the receipt must be read, never inherited as authority.
        edited = await clients['employee'].post('/api/v1/work-items/' + target + '/progress',
            json={'expectedRevision': 1, 'title': '客户方案', 'blocker': '等待确认'})
        assert edited.status_code == 200, edited.text
        context, sent = await turn(setup, conv, '把刚才工作的下一步改为联系客户')
        context.work_change_model = PlanJudge({'nextStep': ('set', '下一步改为联系客户', None)})
        context.intent_model = ReceiptJudge(required_fields=['nextStep'], requested_changes=[{
            'quote': '下一步改为联系客户', 'field': 'nextStep', 'kind': 'next_action'}])
    else:
        await create(clients['employee'], status='done', summary='完成报价')
        previous, _ = await turn(setup, conv, '生成今天日报')
        card = await execute(previous, step=1, action='generate_report', report_date=now().astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat())
        assert card['state'] == 'running'
        await finish(previous)
        target = card['objectId']
        child = await running_context(settings, sessions, users['employee'], {'jobId': card['job']['id']})
        from app.agent.tools.reports import draft_report
        await draft_report.coroutine(completed='完成报价', ongoing='', blockers='', next='', runtime=SimpleNamespace(context=child))
        await finish(child)
        context, sent = await turn(setup, conv, '提交刚才生成的日报')
    if not seeded:
        monkeypatch.setattr(catalog, 'previous_receipt_groups', lambda _: set())
    model = ContinuationModel(model='controlled', api_key='no-network', kind=kind, target=target)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await invoke_harness(context, saver, '按本轮真实用户请求执行', model)
    assert len(model.offered) == (2 if seeded else 3)
    assert ('execute_business_action' in model.offered[0]) is seeded
    assert len(context.intent_model.inputs) == 1
    assert len(model.reads) == 1
    async with sessions() as db:
        rows = (await db.scalars(select(BusinessAction).where(BusinessAction.message_id == sent['messageId']))).all()
        assert len(rows) == 1
        saved = rows[0]
        if kind == 'work':
            record = await db.get(WorkItem, target)
            assert saved.state == 'succeeded' and record.revision == 3
            assert record.content['nextStep'] == '联系客户' and record.content['blocker'] == '等待确认'
            assert model.reads[0]['revision'] == 2
            assert len(context.work_change_model.inputs) == 1
        else:
            record = await db.get(Report, target)
            assert saved.state == 'pending' and record.published_revision == 0
    if kind == 'reports':
        confirmed = await clients['employee'].post('/api/v1/business-actions/' + saved.id + '/confirm', json={'expectedRevision': saved.revision})
        assert confirmed.status_code == 200 and confirmed.json()['state'] == 'succeeded'
        async with sessions() as db:
            record = await db.get(Report, target)
            assert record.published_revision == record.revision
    await finish(context)
    print('receipt_preload', {'kind': kind, 'seeded': seeded, 'main_calls': len(model.offered), 'authorization_calls': 1, 'real_reads': 1, 'receipts': 1})


class AnswerModel(ReviewedFixtureModel):
    offered: list = Field(default_factory=list)
    async def _agenerate(self, messages, **kwargs):
        self.offered.append([tool['function']['name'] for tool in kwargs.get('tools', [])])
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content='这是独立的普通知识回答。'))])


async def test_unrelated_answer_never_writes_and_next_turn_clears_seed(setup):
    conv = await conversation(setup[3]['employee'])
    await prior_work(setup, conv)
    for index in range(2):
        context, sent = await turn(setup, conv, '解释一下列表，不操作工作')
        model = AnswerModel(model='controlled', api_key='no-network')
        async with AsyncPostgresSaver.from_conn_string(setup[0].checkpoint_url) as saver:
            assert await invoke_harness(context, saver, '解释一下列表，不操作工作', model) == '这是独立的普通知识回答。'
        assert len(model.offered) == 1
        assert ('execute_business_action' in model.offered[0]) is (index == 0)
        async with context.sessions() as db:
            assert await db.scalar(select(func.count()).select_from(BusinessAction).where(BusinessAction.message_id == sent['messageId'])) == 0
        assert not context.intent_model.inputs
        await finish(context)


@pytest.mark.parametrize('boundary', ['failed', 'pending', 'deleted', 'revoked', 'ordinary', 'inherited', 'forged'])
async def test_invalid_or_nonbusiness_adjacent_turn_never_falls_back_to_older_success(setup, boundary):
    conv = await conversation(setup[3]['employee'])
    older, _ = await prior_work(setup, conv)
    if boundary == 'pending':
        prior, last = await turn(setup, conv, '先给我确认，再创建第二个工作')
        async with setup[1].begin() as db:
            job = await db.get(Job, prior.job_id)
            job.result = {**job.result, 'executionMode': 'ask'}
            (await db.get(Member, prior.owner_id)).execution_mode = 'ask'
        card = await execute(prior, step=1, action='create_work', changes={'title': '第二个工作'})
        assert card['state'] == 'pending'
        await finish(prior)
    elif boundary in ('failed', 'deleted', 'revoked'):
        card, last = await prior_work(setup, conv, '第二个工作')
    else:
        prior, last = await turn(setup, conv, '普通问题，不操作工作')
        await finish(prior)
    async with setup[1].begin() as db:
        latest = await db.get(Message, last['messageId'])
        if boundary == 'failed':
            (await db.get(BusinessAction, card['id'])).state = boundary
        elif boundary == 'deleted':
            latest.deleted = True
        elif boundary == 'revoked':
            latest.access = {**latest.access, 'invalidated': True}
        elif boundary == 'inherited':
            job = await db.get(Job, last['jobId'])
            job.result = {**job.result, 'taskItems': [{'id': 'inherited', 'receiptId': older['id']}]}
        elif boundary == 'forged':
            latest.reply = json.dumps({'currentActions': [{'id': older['id'], 'action': 'create_work', 'state': 'succeeded'}]})
    current, _ = await turn(setup, conv, '继续看看')
    assert await groups(current) == []
    assert current.context_sources['previousMessageId'] == last['messageId']
    if boundary == 'inherited':
        reference = next(row for row in current.conversation_references if row['id'] == last['messageId'])
        assert reference['currentActions'][0]['id'] == older['id']


async def test_new_conversation_other_users_and_role_change_do_not_inherit_groups(setup):
    conv = await conversation(setup[3]['employee'])
    await prior_work(setup, conv)
    for who in ('employee', 'peer', 'outsider'):
        other = await conversation(setup[3][who])
        context, _ = await turn(setup, other, '新会话', who)
        assert await groups(context) == []
        await finish(context)
    async with setup[1].begin() as db:
        (await db.get(Member, setup[2]['employee'].id)).role = 'admin'
    current, _ = await turn(setup, conv, '现在只看普通问题')
    current.role = 'admin'
    assert await groups(current) == []


async def test_preloaded_work_still_requires_new_authorization_and_own_sources(setup):
    from app.agent.tools.work import get_work_item
    from test_business_actions import read_work
    conv = await conversation(setup[3]['employee'])
    prior, _ = await prior_work(setup, conv)
    current, sent = await turn(setup, conv, '只谈想法，不要修改工作')
    assert await groups(current) == ['work']
    for who in ('peer', 'outsider'):
        foreign = await create(setup[3][who])
        denied = await get_work_item.coroutine(foreign['id'], SimpleNamespace(context=current))
        assert denied.startswith('工作记录不存在或无权查看。')
        assert foreign['id'] not in current.read_versions
    await read_work(current, prior['objectId'])
    current.intent_model = ReceiptJudge(allowed=False)
    rejected = await execute(current, step=1, action='update_work', target_id=prior['objectId'],
                             expected_revision=1, changes={'nextStep': '未被请求的修改'})
    assert rejected['state'] == 'clarification' and len(current.intent_model.inputs) == 1
    async with setup[1]() as db:
        saved = await db.get(WorkItem, prior['objectId'])
        assert saved.revision == 1 and saved.content['nextStep'] == ''
        assert await db.scalar(select(func.count()).select_from(BusinessAction).where(BusinessAction.message_id == sent['messageId'])) == 0


@pytest.mark.parametrize('child_state,expected', [('queued', ['reports']), ('failed', [])])
async def test_report_acceptance_is_not_completion_and_failed_child_is_not_seed(setup, child_state, expected):
    conv = await conversation(setup[3]['employee'])
    await create(setup[3]['employee'], status='done', summary='完成报价')
    previous, _ = await turn(setup, conv, '生成今天日报')
    card = await execute(previous, step=1, action='generate_report', report_date=now().astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat())
    assert card['state'] == 'running'
    await finish(previous)
    async with setup[1].begin() as db:
        (await db.get(Job, card['job']['id'])).state = child_state
    current, _ = await turn(setup, conv, '看看处理到哪里了')
    assert await groups(current) == expected
    async with setup[1]() as db:
        report = await db.get(Report, card['objectId'])
        assert report.published_revision == 0
    assert not current.read_versions and not current.authorization_outcomes
    current.role = 'employee'
    assert not (catalog.visible_tools(current, ['reports']) & catalog.TEAM_TOOL_NAMES)
