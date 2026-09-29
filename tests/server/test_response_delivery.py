"""Completion contract and direct delivery through the real worker graph."""
import json
import pytest
from pydantic import Field
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from fakes import ReviewedFixtureModel, completion
from app.tasks.handlers import process_job
from app.tasks.queue import claim
from app.tasks.models import Job
from app.agent.delivery import Delivery
from test_company import send

pytestmark = pytest.mark.asyncio


class DeliveryModel(ReviewedFixtureModel):
    answer: str = '这是完整答复。'
    calls: int = 0
    raw_first: bool = False
    invalid: bool = False
    mixed: bool = False
    verification_requested: bool = False
    verification_quote: str = ''
    task: dict = Field(default_factory=lambda: {'state': 'completed'})
    async def ainvoke(self, input, config=None, *, stop=None, **kwargs):
        # This fixture deliberately exercises raw protocol replies as well.
        return await super(ReviewedFixtureModel, self).ainvoke(input, config, stop=stop, **kwargs)
    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        if self.invalid or self.raw_first and self.calls == 1:
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
    from test_company import keyed
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


@pytest.mark.parametrize('answer', ['你好，有什么想一起梳理的？', '## 提案\n\n第一步核实范围。\n\n|阶段|产出|\n|---|---|\n|准备|清单|', '今天的书展已开幕。\n\n来源：[城市公告](https://example.org/news)'])
async def test_ordinary_answer_is_delivered_whole_without_second_model_call(setup, answer):
    fake = model(answer=answer)
    result, stored = await run(setup, fake)
    assert result['reply'] == answer, result
    assert result['job']['taskOutcome']['state'] == 'completed'
    assert not any(node['kind'] == 'review' for node in result['job']['nodes'])
    assert fake.calls == 1 and not stored.get('replyReview')


async def test_plain_text_is_recovered_once_into_completion_without_business_replay(setup):
    fake = model(raw_first=True)
    result, stored = await run(setup, fake)
    assert result['reply'] == fake.answer and fake.calls == 2, result
    assert stored['deliveryRepairs'] == ['protocol']
    assert result['job']['taskOutcome']['state'] == 'completed'


async def test_missing_completion_protocol_fails_boundedly_instead_of_false_success(setup):
    fake = model(invalid=True)
    result, stored = await run(setup, fake)
    assert fake.calls == 2 and stored['deliveryRepairs'] == ['protocol']
    assert result['job']['state'] == 'awaiting_retry' and result['job']['taskOutcome']['state'] == 'blocked'
    assert fake.answer not in result['reply']


async def test_completion_and_write_in_same_batch_execute_neither_before_repair(setup):
    fake = model(mixed=True)
    result, _ = await run(setup, fake)
    assert fake.calls == 2 and result['reply'] == fake.answer, result['job']
    assert not result['actions']
    assert (await setup[3]['employee'].get('/api/v1/work-items')).json()['items'] == []


async def test_concrete_missing_information_persists_without_review(setup):
    fake = model(answer='请选择你要分析的那份文件。', task={'goal': '分析文件', 'state': 'needs_input', 'remaining': ['需要选择文件']})
    result, stored = await run(setup, fake)
    assert result['job']['taskOutcome']['state'] == 'needs_input'
    assert result['job']['taskOutcome']['remaining'] == ['需要选择文件']
    assert stored['taskInterpretation']['goal'] == '分析文件' and fake.calls == 1


async def test_summary_does_not_accept_empty_success_or_incoherent_state():
    with pytest.raises(ValueError):
        Delivery(answer='', task={'state': 'completed'})
    with pytest.raises(ValueError):
        Delivery(answer='还缺文件', task={'state': 'completed', 'remaining': ['文件']})


class ExhaustingModel(DeliveryModel):
    offered: list = Field(default_factory=list)
    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        self.offered.append([tool['function']['name'] for tool in kwargs['tools']])
        if self.calls == 1:
            answer = AIMessage(content='', tool_calls=[{'id': f'query-{i}', 'name': 'find_work_items', 'args': {'query': f'项目{i}'}} for i in range(18)])
        else:
            answer = completion('本轮已查到的工作列表为空；最后两次查询未执行。', task={'state': 'blocked', 'remaining': ['最后两次查询超出本轮额度']})
        return ChatResult(generations=[ChatGeneration(message=answer)])


async def test_parallel_tool_batch_exhaustion_still_delivers_without_raising_budget(setup):
    fake = ExhaustingModel(model='controlled', api_key='controlled')
    result, _ = await run(setup, fake, '请分别查询十八个不同项目')
    assert fake.calls == 2 and fake.offered[-1] == ['finish_task'], result
    assert '最后两次查询未执行' in result['reply']
    assert result['job']['taskOutcome']['state'] == 'blocked'
    assert len([node for node in result['job']['nodes'] if node['kind'] == 'tool']) == 16
    assert not result['job']['error']


@pytest.mark.parametrize('legacy', [True, False])
async def test_pending_completion_upgrade_and_correction_survive_review_retry(setup, monkeypatch, legacy):
    from app.agent.delivery import ReviewedReply
    from app.tasks.node_execution import initialize
    from fakes import set_delivery
    from test_company import keyed
    calls, assessments = [], []
    first_initialization = True

    async def with_old_cache(context, input_key):
        nonlocal first_initialization
        await initialize(context, input_key)
        if legacy and first_initialization:
            async with context.sessions.begin() as db:
                job = await db.get(Job, context.job_id)
                job.result = {**job.result, 'pendingReply': {'input': input_key, 'answer': '旧缓存答复', 'evidence': []}}
        first_initialization = False

    async def graph(context, *args, **kwargs):
        calls.append(True)
        await set_delivery(context, '升级后的答复' if legacy else '不完整正文', business=True)
        if not legacy:
            context.delivery.update(response_complete=False, response_issue='缺少方案')
        return context.delivery['answer']

    async def assess(context, answer, **kwargs):
        assessments.append(answer)
        if not legacy and len(assessments) == 1:
            return ReviewedReply(answer, verified=True, needs_response=True, response_reason='缺少方案', task=context.delivery['task'])
        if len(assessments) == (1 if legacy else 2):
            return ReviewedReply(error_code='ControlledReviewFailure', task=context.delivery['task'])
        assert context.delivery['answer'] == answer
        assert context.delivery.get('response_complete', True)
        return ReviewedReply(answer, verified=True, task=context.delivery['task'])

    async def correct(*args, **kwargs):
        return '完整方案正文'

    monkeypatch.setattr('app.tasks.node_execution.initialize', with_old_cache)
    monkeypatch.setattr('app.tasks.handlers.invoke_harness', graph)
    monkeypatch.setattr('app.agent.delivery.assess', assess)
    monkeypatch.setattr('app.agent.response_repair.repair_response', correct)
    result, stored = await run(setup, object())
    expected = '升级后的答复' if legacy else '完整方案正文'
    assert result['job']['state'] == 'awaiting_retry'
    assert stored['pendingReply']['deliveryVersion'] == 1
    assert stored['pendingReply']['answer'] == stored['pendingReply']['delivery']['answer'] == expected
    assert stored['pendingReply']['delivery']['response_complete']
    settings, sessions, users, clients = setup
    assert (await clients['employee'].post('/api/v1/jobs/' + result['job']['id'] + '/retry', json={}, headers=keyed())).status_code == 200
    job = await claim(sessions, users['employee'].id)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(job, sessions, settings, saver, model=object())
    detail = (await clients['employee'].get('/api/v1/messages/' + result['id'])).json()
    assert detail['reply'] == expected and len(calls) == 1, detail


async def test_execution_only_issue_cannot_finish_as_completed_without_receipt(setup):
    from test_business_actions import run_reply, ReplyJudge
    result = await run_reply(setup, '创建工作甲', '已创建工作甲。', ReplyJudge(['execution']))
    assert not result['actions']
    assert '已创建工作甲' not in result['reply']
    assert result['job']['taskOutcome']['state'] != 'completed', result


async def test_failed_correction_keeps_safe_prose_and_resumes_the_same_node(setup, monkeypatch):
    from app.agent.delivery import ReviewedReply
    from app.tasks.node_execution import execute_node
    from app.integrations.models.transport import ProviderError
    from fakes import set_delivery
    graph_calls, repair_calls = [], []
    available = False

    async def graph(context, *args, **kwargs):
        graph_calls.append(True)
        await set_delivery(context, '已核实部分。尚缺解释。', business=True)
        return context.delivery['answer']

    async def assess(context, answer, **kwargs):
        if answer == '已核实部分。完整解释。':
            return ReviewedReply(answer, verified=True, task=context.delivery['task'])
        return ReviewedReply('已核实部分。', verified=True, needs_response=True, response_reason='缺少解释', task=context.delivery['task'])

    async def correct(context, *args, **kwargs):
        async def operation():
            repair_calls.append(True)
            if not available:
                raise ProviderError('authentication', '受控修正失败', 401)
            return '已核实部分。完整解释。'
        return await execute_node(context, identity='same-correction', kind='model', label='完善答复中', operation=operation)

    monkeypatch.setattr('app.tasks.handlers.invoke_harness', graph)
    monkeypatch.setattr('app.agent.delivery.assess', assess)
    monkeypatch.setattr('app.agent.response_repair.repair_response', correct)
    result, stored = await run(setup, object())
    assert result['job']['state'] == 'awaiting_retry', result
    assert '已核实部分。' in result['reply'] and '尚缺解释' not in result['reply']
    assert stored['pendingReply']['safeReply'] == '已核实部分。'
    assert stored['deliveryRepairs'] == ['response']
    available = True
    settings, sessions, users, clients = setup
    assert (await clients['employee'].post('/api/v1/jobs/' + result['job']['id'] + '/retry', json={})).status_code == 200
    job = await claim(sessions, users['employee'].id)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(job, sessions, settings, saver, model=object())
    detail = (await clients['employee'].get('/api/v1/messages/' + result['id'])).json()
    assert detail['reply'] == '已核实部分。完整解释。', detail
    assert len(graph_calls) == 1 and len(repair_calls) == 2
    assert len(detail['job']['nodes']) == 1


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


@pytest.mark.parametrize('verify,quote,count,state', [
    (False, '', 0, 'awaiting_input'),
    (True, '核验这份材料的结论', 1, 'awaiting_input'),
    (True, '用户从没说过的核验要求', 0, 'awaiting_retry'),
])
async def test_only_explicit_fact_verification_with_current_user_quote_routes_to_review(setup, verify, quote, count, state):
    fake = RoutingModel(model='controlled', api_key='controlled', verification_requested=verify, verification_quote=quote)
    result, _ = await run(setup, fake, '请核验这份材料的结论' if verify else '查公开资料并附来源')
    assert fake.reviews == count and fake.calls == 1
    assert len([node for node in result['job']['nodes'] if node['kind'] == 'review']) == count
    assert result['job']['state'] == state, result
    if count:
        assert any(node['label'] == '核验事实中' for node in result['job']['nodes'])


@pytest.mark.parametrize('suggestion', [True, False])
async def test_readonly_metadata_cannot_hide_actual_suggestion_or_failed_attempt(setup, monkeypatch, suggestion):
    from types import SimpleNamespace
    from app.agent.tools.work import propose_progress
    from test_assistant_write_scope import ScopeJudge
    from test_business_actions import Judge
    from fakes import set_delivery
    async def graph(context, *args, **kwargs):
        context.intent_model = ScopeJudge(True, preview=True) if suggestion else Judge(False)
        await propose_progress.coroutine('工作甲', '原始计划', 'in_progress', '', '', SimpleNamespace(context=context))
        answer = '建议等待确认。' if suggestion else '这次未执行，缺少明确操作授权。'
        await set_delivery(context, answer, business=False, task={'state': 'needs_confirmation' if suggestion else 'blocked'})
        return answer
    monkeypatch.setattr('app.tasks.handlers.invoke_harness', graph)
    fake = RoutingModel(model='controlled', api_key='controlled')
    result, stored = await run(setup, fake, '先为工作甲准备待确认建议')
    assert fake.reviews == 1
    assert any(node['kind'] == 'review' for node in result['job']['nodes']), result
    assert result['drafts'] if suggestion else stored['toolOutcomes']
    assert result['job']['taskOutcome']['state'] != 'completed'


class IncompleteResponseModel(ReviewedFixtureModel):
    business: bool = True
    correction: str = 'complete'
    calls: int = 0
    reviews: list = Field(default_factory=list)
    corrections: list = Field(default_factory=list)
    async def ainvoke(self, messages, *args, **kwargs):
        try:
            payload = json.loads(messages[-1].content)
        except (ValueError, TypeError):
            payload = {}
        if payload.get('task') == 'business_reply_review':
            self.reviews.append(payload)
            issues = []
            if payload['delivery']['response_complete'] and self.correction == 'incomplete':
                issues = [{'kind': 'missing_response', 'reason': '仍未提供必要分析说明'}]
            return AIMessage(content=json.dumps({'issues': issues}, ensure_ascii=False))
        if 'correction' in payload:
            self.corrections.append(payload)
            if self.correction == 'failure':
                from app.integrations.models.transport import ProviderError
                raise ProviderError('authentication', '受控正文修正失败', 401)
            answer = '分析说明：先核实范围，再对照材料中的依据。' if self.correction == 'complete' else '尚缺分析说明。'
            return AIMessage(content=answer)
        return await super().ainvoke(messages, *args, **kwargs)
    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        if self.business and self.calls == 1:
            result = AIMessage(content='', tool_calls=[{'id': 'save-once', 'name': 'execute_business_action', 'args': {'step': 1, 'action': 'create_work', 'changes': {'title': '待分析方案'}}}])
        else:
            receipts = [json.loads(messages[-1].content)['id']] if self.business else []
            result = completion('已保存工作。' if self.business else '已核对部分结论。', business=self.business,
                operation_ids=receipts, response_complete=False, response_issue='还未提供用户要求的分析说明',
                verification_requested=not self.business, verification_quote='' if self.business else '核验这份材料的结论')
        return ChatResult(generations=[ChatGeneration(message=result)])


@pytest.mark.parametrize('business', [True, False])
@pytest.mark.parametrize('correction', ['complete', 'incomplete', 'failure'])
async def test_known_incomplete_response_survives_empty_targeted_review_and_repairs_once(setup, business, correction):
    fake = IncompleteResponseModel(model='controlled', api_key='controlled', business=business, correction=correction)
    text = '创建工作待分析方案，并提供分析说明。' if business else '请核验这份材料的结论，并解释判断依据。'
    result, stored = await run(setup, fake, text)
    assert fake.calls == (2 if business else 1)
    assert len(fake.corrections) == 1 and len(fake.reviews) == (1 if correction == 'failure' else 2)
    assert not fake.reviews[0]['delivery']['response_complete']
    assert fake.corrections[0]['correction'] == '还未提供用户要求的分析说明'
    assert stored['deliveryRepairs'] == ['response']
    assert (result['job']['taskOutcome']['state'] == 'completed') is (correction == 'complete'), result
    if correction == 'incomplete':
        assert stored['responseRepairComplete'] and stored['completionIssue'] == 'response'
        assert result['job']['incompleteTask']
    elif correction == 'failure':
        assert result['job']['state'] == 'awaiting_retry'
        assert not stored['pendingReply']['delivery']['response_complete']
        fake.correction = 'complete'
        settings, sessions, users, clients = setup
        assert (await clients['employee'].post('/api/v1/jobs/' + result['job']['id'] + '/retry', json={})).status_code == 200
        job = await claim(sessions, users['employee'].id)
        async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
            await process_job(job, sessions, settings, saver, model=fake)
        result = (await clients['employee'].get('/api/v1/messages/' + result['id'])).json()
        assert result['job']['taskOutcome']['state'] == 'completed', result
        assert fake.calls == (2 if business else 1) and len(fake.corrections) == 2
    if correction != 'incomplete':
        assert '分析说明：先核实范围，再对照材料中的依据。' in result['reply']
    works = (await setup[3]['employee'].get('/api/v1/work-items')).json()['items']
    assert len(works) == len(result['actions']) == int(business)
    if business:
        assert result['actions'][0]['state'] == 'succeeded' and works[0]['revision'] == 1
        assert fake.reviews[0]['delivery']['operation_ids'] == [result['actions'][0]['id']]


@pytest.mark.parametrize('verified', [True, False])
async def test_known_response_issue_merges_without_overriding_targeted_review_state(setup, monkeypatch, verified):
    from dataclasses import replace
    from app.agent.delivery import ReviewedReply, assess
    from fakes import set_delivery
    from test_business_actions import runtime
    context, _ = await runtime(setup, '核验这份材料的结论')
    await set_delivery(context, '候选正文')
    context.delivery.update(verification_requested=True, verification_quote='核验这份材料的结论', response_complete=False, response_issue='缺少分析说明')
    reviewed = ReviewedReply('无争议正文', execution_claims=True, verified=verified, needs_action=True, needs_response=True,
        response_reason='核对发现事实冲突', error_code='' if verified else 'ControlledReviewFailure',
        error_message='' if verified else '专项核对失败', task={'state': 'blocked'})
    async def review(*args, **kwargs):
        return reviewed
    monkeypatch.setattr('app.agent.reply_review.review_reply', review)
    result = await assess(context, context.delivery['answer'])
    expected = replace(reviewed, response_reason='核对发现事实冲突；缺少分析说明') if verified else reviewed
    assert result == expected
