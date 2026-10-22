"""Completion contract and direct delivery through the real worker graph."""
import json
import pytest
from pydantic import Field
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from _support.agent.fakes import ReviewedFixtureModel, completion
from app.tasks.processing.handlers import process_job
from app.tasks.runtime.queue import claim
from app.tasks.models import Job
from app.agent.completion.delivery import Delivery
from _support.http.company import send
from _support.agent.response_delivery import DeliveryModel, PageDeliveryModel, RoutingModel, model, run

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('answer', ['你好，有什么想一起梳理的？', '## 提案\n\n第一步核实范围。\n\n|阶段|产出|\n|---|---|\n|准备|清单|', '今天的书展已开幕。\n\n来源：[城市公告](https://example.org/news)'])
async def test_ordinary_answer_is_delivered_whole_without_second_model_call(setup, answer):
    fake = model(answer=answer)
    result, stored = await run(setup, fake)
    assert result['reply'] == answer, result
    assert result['job']['taskOutcome']['state'] == 'completed'
    assert not any(node['kind'] == 'review' for node in result['job']['nodes'])
    assert fake.calls == 1 and not stored.get('replyReview')


async def test_plain_text_is_delivered_once_without_business_replay_or_wrapping(setup):
    fake = model(raw_first=True)
    result, stored = await run(setup, fake)
    assert result['reply'] == fake.answer and fake.calls == 1, result
    assert not stored.get('deliveryRepairs')
    assert result['job']['taskOutcome']['state'] == 'completed'
    assert 'finish_task' not in fake.requests[0]['tools'] and fake.requests[0]['tool_choice'] == 'auto'


async def test_missing_completion_protocol_fails_boundedly_instead_of_false_success(setup):
    fake = model(invalid=True, answer='<!--noria:{broken-->invalid')
    result, stored = await run(setup, fake)
    assert fake.calls == 1 and not stored.get('deliveryRepairs')
    assert result['job']['state'] == 'failed' and result['job']['taskOutcome']['state'] == 'blocked'
    assert fake.answer not in result['reply']


class PreviousReceiptModel(DeliveryModel):
    receipt_id: str = ''
    repeat_invalid: bool = False
    repair_errors: list = Field(default_factory=list)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        self.requests.append({'tools': [tool['function']['name'] for tool in kwargs.get('tools', [])], 'tool_choice': kwargs.get('tool_choice')})
        errors = [message for message in messages if isinstance(message, ToolMessage)
                  and message.name == 'finish_task' and message.status == 'error']
        if self.raw_first and self.calls == 1:
            result = AIMessage(content=self.answer)
        else:
            if errors:
                self.repair_errors = [message.content for message in errors]
                assert '此前消息' in errors[-1].content
                assert self.requests[-1]['tools'] == [] and self.requests[-1]['tool_choice'] in (None, 'none')
            invalid = not errors or self.repeat_invalid
            result = (completion(self.answer, business=True, operation_ids=[self.receipt_id])
                      if invalid else AIMessage(content=self.answer))
        return ChatResult(generations=[ChatGeneration(message=result)])


@pytest.mark.parametrize('raw_first', [False, True])
@pytest.mark.parametrize('repeat_invalid', [False, True])
async def test_previous_message_receipt_repairs_first_terminal_reference_without_writing(setup, raw_first, repeat_invalid):
    from app.agent.actions.operations import execute
    from _support.agent.business_actions import finish, runtime
    context, sent = await runtime(setup, '创建报价方案，截止日期设为2026年10月2日')
    receipt = await execute(context, step=1, action='create_work', changes={'title': '报价方案', 'dueDate': '2026-10-02'})
    assert receipt['state'] == 'succeeded'
    await finish(context)
    client = setup[3]['employee']
    path = '/api/v1/work-items/' + receipt['objectId']
    before = (await client.get(path)).json()
    answer = '最后设置的截止日期是2026年10月2日；本轮仅查询，状态保持原样，没有新增进展。'
    fake = PreviousReceiptModel(model='controlled', api_key='controlled', answer=answer,
        receipt_id=receipt['id'], raw_first=raw_first, repeat_invalid=repeat_invalid)
    result, stored = await run(setup, fake, '状态保持原样，告诉我最后设置的是哪一天，不要新增进展',
        conversationId=sent['conversationId'], workReference={'workId': receipt['objectId']})
    if raw_first:
        assert fake.calls == 1 and not stored.get('deliveryRepairs')
        assert result['reply'] == answer and not result['actions']
        assert (await client.get(path)).json() == before
        return
    assert fake.calls == 2 and fake.repair_errors
    assert stored['deliveryRepairs'] == (['protocol', 'references'] if raw_first else ['protocol'])
    assert not result['actions'] and not stored.get('toolOutcomes')
    assert (await client.get(path)).json() == before
    assert (await client.get(path + '/updates')).json()['items'] == []
    if repeat_invalid:
        assert result['job']['state'] in ('failed', 'awaiting_retry')
        assert answer not in result['reply'] and '有效收尾' in result['job']['error']
        assert result['job']['taskOutcome']['state'] == 'blocked'
    else:
        assert result['job']['state'] == 'awaiting_input' and result['job']['taskOutcome']['state'] == 'completed'
        assert result['reply'] == answer
        assert not stored.get('pendingReply') and not stored.get('replyReviewError')


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
    query_count: int = 66
    with_receipt: bool = False
    answer: str = '本轮已查到的工作列表为空；最后两次查询未执行。'

    async def ainvoke(self, input, config=None, *, stop=None, **kwargs):
        if self.with_receipt and isinstance(input, list) and isinstance(input[-1], HumanMessage):
            try:
                payload = json.loads(input[-1].content)
            except (ValueError, TypeError):
                payload = {}
            if payload.get('proposedOperation'):
                return AIMessage(content=json.dumps({'allowed': True, 'quote': payload['currentUserText'], 'reason': '', 'receiptOnly': False}))
        return await super().ainvoke(input, config, stop=stop, **kwargs)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        self.offered.append([tool['function']['name'] for tool in kwargs.get('tools', [])])
        if self.calls == 1:
            assert self.offered[-1] == ['load_tools', 'request_user_input', 'web_search']
            answer = AIMessage(content='', tool_calls=[{'id': 'load-work', 'name': 'load_tools', 'args': {'groups': ['work']}}])
        elif self.with_receipt and self.calls == 2:
            assert 'execute_business_action' in self.offered[-1]
            answer = AIMessage(content='', tool_calls=[{'id': 'create-once', 'name': 'execute_business_action', 'args': {'step': 1, 'action': 'create_work', 'changes': {'title': '已保存工作'}}}])
        elif self.calls == (3 if self.with_receipt else 2):
            assert 'find_work_items' in self.offered[-1]
            answer = AIMessage(content='', tool_calls=[{'id': f'query-{i}', 'name': 'find_work_items', 'args': {'query': f'项目{i}'}} for i in range(self.query_count)])
        else:
            # LangChain skips tool binding entirely for an empty visible set.
            assert self.offered[-1] == [] and kwargs.get('tool_choice') in (None, 'none')
            answer = AIMessage(content='<!--noria:{}-->\n' + self.answer)
        return ChatResult(generations=[ChatGeneration(message=answer)])


@pytest.mark.parametrize('previous_pending', [False, True])
async def test_parallel_tool_batch_exhaustion_still_delivers_without_raising_budget(setup, previous_pending):
    from app.modules.conversations.models import ConversationTaskState
    from sqlalchemy import select
    conversation = {}
    if previous_pending:
        from _support.agent.prose_delivery import ProseModel
        prior, _ = await run(setup, ProseModel(model='controlled', api_key='controlled', answer='请提供文件。', task_value={'state': 'needs_input', 'remaining': ['缺少指定文件']}))
        conversation['conversationId'] = prior['conversationId']
    # One branch omits any prose explanation: status must come from the refusal.
    answer = '本轮已查到的工作列表为空。' if previous_pending else '本轮已查到的工作列表为空；最后两次查询未执行。'
    fake = ExhaustingModel(model='controlled', api_key='controlled', answer=answer)
    result, stored = await run(setup, fake, '请分别查询六十六个不同项目', **conversation)
    assert fake.calls == 3 and fake.offered[-1] == [], result
    assert answer in result['reply']
    assert result['job']['taskOutcome']['state'] == 'blocked'
    assert len([node for node in result['job']['nodes'] if node['kind'] == 'tool']) == 64
    remaining = stored['nodeExecution']['budgetBlockedTools']
    assert len(remaining) == 2 and all('查找工作：项目' in step and '未执行' in step for step in remaining)
    assert result['job']['incompleteTask'] and result['job']['taskOutcome']['remaining'] == remaining
    assert stored['taskInterpretation']['state'] == 'blocked' and stored['taskInterpretation']['remaining'] == remaining
    assert not stored.get('deliveryRepairs')
    assert not result['job']['error']
    async with setup[1]() as db:
        state = await db.scalar(select(ConversationTaskState).where(ConversationTaskState.conversation_id == result['conversationId']))
        assert state.payload['task']['state'] == 'blocked'
        assert state.payload['task']['remaining'] == remaining
        assert state.payload['task']['messageId'] == result['id']


@pytest.mark.parametrize('query_count', [64])
async def test_budget_closeout_after_all_reads_does_not_invent_unfinished_steps(setup, query_count):
    fake = ExhaustingModel(model='controlled', api_key='controlled', query_count=query_count, answer='全部查询均已完成，没有匹配的工作。')
    result, stored = await run(setup, fake, f'请分别查询{query_count}个不同项目')
    assert fake.calls == 3 and fake.offered[-1] == []
    assert len([node for node in result['job']['nodes'] if node['kind'] == 'tool']) == query_count
    assert result['job']['taskOutcome']['state'] == 'completed'
    assert result['job']['taskOutcome']['remaining'] == [] and not result['job']['incompleteTask']
    assert not stored['nodeExecution'].get('budgetBlockedTools')


async def test_budget_prose_keeps_committed_receipt_without_replaying_write(setup):
    fake = ExhaustingModel(model='controlled', api_key='controlled', with_receipt=True, answer='已保存工作；查询尚未全部完成。')
    result, stored = await run(setup, fake, '创建工作“已保存工作”，然后分别查询六十六个不同项目')
    assert fake.calls == 4 and fake.offered[-1] == []
    tools = [node for node in result['job']['nodes'] if node['kind'] == 'tool']
    assert len(tools) == 64 and sum(node['label'] == '创建工作' for node in tools) == 1
    assert len(result['actions']) == 1 and result['actions'][0]['state'] == 'succeeded'
    works = (await setup[3]['employee'].get('/api/v1/work-items')).json()['items']
    assert len(works) == 1 and works[0]['id'] == result['actions'][0]['objectId']
    outcome = result['job']['taskOutcome']
    assert result['job']['incompleteTask'] and outcome['state'] == 'partial'
    assert len(outcome['completed']) == 1 and len(outcome['remaining']) == 3
    assert outcome['remaining'] == stored['nodeExecution']['budgetBlockedTools']
    assert not stored.get('deliveryRepairs')


async def test_budget_refusals_survive_same_scope_recovery_but_not_new_input(setup):
    from app.agent.completion.prose import task_for
    from app.agent.runtime.tool_nodes import reject_tool_budget
    from app.tasks.nodes.node_execution import initialize
    from _support.agent.business_actions import runtime
    context, _ = await runtime(setup, '查询项目甲')
    context.node_retry = True
    await initialize(context, 'original-input')
    call = {'id': 'refused-query', 'name': 'find_work_items', 'args': {'query': '项目甲'}}
    await reject_tool_budget(context, call)
    await initialize(context, 'original-input')
    async with context.sessions() as db:
        stored = await db.get(Job, context.job_id)
        task = task_for(stored, {'state': 'completed'})
        assert task.state == 'blocked' and len(task.remaining) == 1
        merged = task_for(stored, {'state': 'needs_input', 'remaining': ['缺少文件']})
        assert merged.state == 'blocked' and merged.remaining == ['缺少文件', *task.remaining]
    await initialize(context, 'corrected-input')
    async with context.sessions() as db:
        stored = await db.get(Job, context.job_id)
        assert task_for(stored).state == 'completed'
        assert not stored.result['nodeExecution'].get('budgetBlockedTools')


@pytest.mark.parametrize('legacy', [True, False])
async def test_pending_completion_upgrade_and_correction_survive_review_retry(setup, monkeypatch, legacy):
    from app.agent.completion.delivery import ReviewedReply
    from app.tasks.nodes.node_execution import initialize
    from _support.agent.fakes import set_delivery
    from _support.http.company import keyed
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

    monkeypatch.setattr('app.tasks.nodes.node_execution.initialize', with_old_cache)
    monkeypatch.setattr('app.tasks.processing.handlers.invoke_harness', graph)
    monkeypatch.setattr('app.agent.completion.delivery.assess', assess)
    monkeypatch.setattr('app.agent.completion.recovery.response_repair.repair_response', correct)
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
    from _support.agent.business_actions import run_reply, ReplyJudge
    result = await run_reply(setup, '创建工作甲', '已创建工作甲。', ReplyJudge(['execution']))
    assert not result['actions']
    assert '已创建工作甲' not in result['reply']
    assert result['job']['taskOutcome']['state'] != 'completed', result


async def test_failed_correction_keeps_safe_prose_and_resumes_the_same_node(setup, monkeypatch):
    from app.agent.completion.delivery import ReviewedReply
    from app.tasks.nodes.node_execution import execute_node
    from app.integrations.models.transport import ProviderError
    from _support.agent.fakes import set_delivery
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

    monkeypatch.setattr('app.tasks.processing.handlers.invoke_harness', graph)
    monkeypatch.setattr('app.agent.completion.delivery.assess', assess)
    monkeypatch.setattr('app.agent.completion.recovery.response_repair.repair_response', correct)
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


@pytest.mark.parametrize('verify', [False, True])
async def test_reading_and_explicit_verification_deliver_without_an_extra_judge(setup, monkeypatch, verify):
    async def fetch(url, **kwargs):
        return {'url': url, 'title': 'API reference', 'text': 'Widget.run() returns its result when finished.',
                'evidenceType': 'page_text', 'offset': 0, 'truncated': False, 'nextOffset': None}
    monkeypatch.setattr('app.integrations.web_research.web_fetch', fetch)
    fake = PageDeliveryModel(model='controlled', api_key='unused', answer='`Widget.run()` 完成后返回结果。',
                             verification_requested=verify, verification_quote='核验这个方法的行为' if verify else '')
    result, stored = await run(setup, fake, '核验这个方法的行为' if verify else '阅读文档并解释这个方法')
    assert result['reply'] == fake.answer and result['job']['taskOutcome']['state'] == 'completed'
    assert fake.calls == 2 and fake.reviews == 0
    assert sum(node['kind'] == 'review' for node in result['job']['nodes']) == 0
    assert stored['webSources']['https://example.org/reference']['fetchState'] == 'read'


@pytest.mark.parametrize('verify,quote,count,state', [
    (False, '', 0, 'awaiting_input'),
    (True, '核验这份材料的结论', 0, 'awaiting_input'),
    (True, '用户从没说过的核验要求', 0, 'failed'),
])
async def test_explicit_verification_is_delivered_directly_but_quote_must_match_request(setup, verify, quote, count, state):
    fake = RoutingModel(model='controlled', api_key='controlled', verification_requested=verify, verification_quote=quote, repeat_invalid_protocol=state == 'failed')
    result, _ = await run(setup, fake, '请核验这份材料的结论' if verify else '查公开资料并附来源')
    assert fake.reviews == count and fake.calls == (2 if state == 'failed' else 1)
    assert len([node for node in result['job']['nodes'] if node['kind'] == 'review']) == count
    assert result['job']['state'] == state, result
    if state == 'failed':
        assert '有效收尾' in result['job']['error'] and fake.answer not in result['reply']
    if count:
        assert any(node['label'] == '核验事实中' for node in result['job']['nodes'])


@pytest.mark.parametrize('suggestion', [True, False])
async def test_readonly_metadata_cannot_hide_actual_suggestion_or_failed_attempt(setup, monkeypatch, suggestion):
    from types import SimpleNamespace
    from app.agent.tools.business.work import propose_progress
    from _support.agent.assistant_write_scope import ScopeJudge
    from _support.agent.business_actions import Judge
    from _support.agent.fakes import set_delivery
    async def graph(context, *args, **kwargs):
        context.intent_model = ScopeJudge(True, preview=True) if suggestion else Judge(False)
        await propose_progress.coroutine('工作甲', '原始计划', 'in_progress', '', '', SimpleNamespace(context=context))
        answer = '建议等待确认。' if suggestion else '这次未执行，缺少明确操作授权。'
        await set_delivery(context, answer, business=False, task={'state': 'needs_confirmation' if suggestion else 'blocked'})
        return answer
    monkeypatch.setattr('app.tasks.processing.handlers.invoke_harness', graph)
    fake = RoutingModel(model='controlled', api_key='controlled')
    result, stored = await run(setup, fake, '先为工作甲准备待确认建议')
    assert fake.reviews == 0
    assert not stored.get('replyReview')
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
            completeness = payload.get('delivery', payload.get('responseCompleteness', {}))
            if completeness['response_complete'] and self.correction == 'incomplete':
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
@pytest.mark.parametrize('correction', ['complete', 'failure'])
async def test_declared_incomplete_response_repairs_once_without_a_second_judge(setup, business, correction):
    fake = IncompleteResponseModel(model='controlled', api_key='controlled', business=business, correction=correction)
    text = '创建工作待分析方案，并提供分析说明。' if business else '请核验这份材料的结论，并解释判断依据。'
    result, stored = await run(setup, fake, text)
    assert fake.calls == (2 if business else 1)
    assert len(fake.corrections) == 1 and not fake.reviews
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
        assert not stored.get('replyReview')


async def test_declared_response_issue_preserves_task_without_calling_a_judge(setup, monkeypatch):
    from app.agent.completion.delivery import assess
    from _support.agent.fakes import set_delivery
    from _support.agent.business_actions import runtime
    context, _ = await runtime(setup, '核验这份材料的结论')
    await set_delivery(context, '候选正文', task={'state': 'blocked', 'remaining': ['资料未覆盖']})
    context.delivery.update(verification_requested=True, verification_quote='核验这份材料的结论', response_complete=False, response_issue='缺少分析说明')
    async def forbidden(*args, **kwargs):
        pytest.fail('Online completion must not call a model reviewer')
    monkeypatch.setattr('app.agent.completion.review.reply_review.review_reply', forbidden)
    result = await assess(context, context.delivery['answer'])
    assert result.verified and result.text == '候选正文' and result.needs_response
    assert result.response_reason == '缺少分析说明' and result.task == Delivery.model_validate(context.delivery).task.model_dump()


class FileReceiptModel(RoutingModel):
    repeat_invalid: bool = False
    file_receipt: dict = Field(default_factory=dict)
    repair_errors: list = Field(default_factory=list)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            result = AIMessage(content='', tool_calls=[{'id': 'generate-file-once', 'name': 'run_python',
                'args': {'code': 'print(3)', 'title': '计算结果', 'step': 1}}])
        else:
            output = next(message for message in reversed(messages) if isinstance(message, ToolMessage) and message.name == 'run_python')
            self.file_receipt = json.loads(output.content)
            if self.calls == 3:
                assert not kwargs.get('tools') and kwargs.get('tool_choice') in (None, 'none')
                errors = [message.content for message in messages if isinstance(message, ToolMessage) and message.name == 'finish_task' and message.status == 'error']
                assert len(errors) == 1 and '私人成果' in errors[0]
                self.repair_errors = errors
            invalid = self.calls == 2 or self.repeat_invalid
            result = (completion('CSV 文件已生成，可在本轮成果中下载。', business=True,
                operation_ids=[self.file_receipt['delivery']['id']]) if invalid
                else AIMessage(content='CSV 文件已生成，可在本轮成果中下载。'))
        return ChatResult(generations=[ChatGeneration(message=result)])


@pytest.mark.parametrize('repeat_invalid', [False, True])
async def test_file_id_in_business_receipts_repairs_metadata_once_without_reexecuting_file(setup, monkeypatch, repeat_invalid):
    from dataclasses import replace
    from sqlalchemy import func, select
    from app.modules.deliverables.models import DeliverableRevision
    from app.modules.executions.models import SandboxExecution
    from app.modules.work.models import WorkItem
    from _support.agent.sandbox_execution import ReceiptClient
    settings, sessions, users, clients = setup
    settings = replace(settings, sandbox_url='http://controlled-sandbox', sandbox_token='controlled')
    ReceiptClient.runs, ReceiptClient.count = {}, 0
    monkeypatch.setattr('app.modules.executions.service.SandboxClient', ReceiptClient)
    fake = FileReceiptModel(model='controlled', api_key='controlled', repeat_invalid=repeat_invalid)
    result, stored = await run((settings, sessions, users, clients), fake, '生成 CSV 文件，不要创建工作')
    assert fake.calls == 3 and fake.repair_errors
    assert stored['deliveryRepairs'] == ['protocol'] and not stored.get('responseRepairComplete')
    assert sum(node['kind'] == 'review' for node in result['job']['nodes']) == 0
    assert ReceiptClient.count == 1 and len(result['deliverables']) == 1
    file = result['deliverables'][0]['files'][0]
    assert (await clients['employee'].get(file['url'])).content == ReceiptClient.data
    async with sessions() as db:
        for model_type in (SandboxExecution, DeliverableRevision):
            assert await db.scalar(select(func.count()).select_from(model_type).where(model_type.owner_id == users['employee'].id)) == 1
        assert not await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == users['employee'].id))
    if repeat_invalid:
        assert result['job']['state'] == 'failed'
        assert '有效收尾' in result['job']['error']
    else:
        assert result['job']['state'] == 'succeeded' and result['job']['taskOutcome']['state'] == 'completed'
        assert result['reply'] == 'CSV 文件已生成，可在本轮成果中下载。'


class ProtocolThenActionModel(DeliveryModel):
    reviews: int = 0

    async def ainvoke(self, messages, *args, **kwargs):
        try:
            payload = json.loads(messages[-1].content)
        except (ValueError, TypeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if payload.get('proposedOperation'):
            return AIMessage(content=json.dumps({'allowed': True, 'quote': payload['currentUserText'], 'reason': ''}))
        if payload.get('task') == 'business_reply_review':
            self.reviews += 1
            issues = [{'kind': 'missing_action', 'reason': '还缺已授权的第二项工作'}] if len(payload['currentActions']) == 1 else []
            return AIMessage(content=json.dumps({'issues': issues}))
        return await super().ainvoke(messages, *args, **kwargs)

    async def _agenerate(self, messages, *args, **kwargs):
        self.calls += 1
        if self.calls in (1, 5):
            step = 1 if self.calls == 1 else 2
            result = AIMessage(content='', tool_calls=[{'name': 'execute_business_action', 'id': 'create-' + str(step),
                'args': {'step': step, 'action': 'create_work', 'changes': {'title': '工作' + str(step)}}}])
        elif self.calls == 2:
            result = AIMessage(content='', tool_calls=[{'name': 'set_task_context', 'id': 'remaining', 'args': {'business_requested': True, 'task': {'state': 'blocked', 'remaining': ['第二项还未保存']}}}])
        elif self.calls == 3:
            result = AIMessage(content='已保存第一项，第二项还未保存。')
        elif self.calls == 4:
            result = AIMessage(content='', tool_calls=[{'name': 'get_business_actions', 'id': 'receipts', 'args': {}}])
        else:
            receipts = [json.loads(item.content)['id'] for item in messages if isinstance(item, ToolMessage) and item.name == 'execute_business_action']
            result = completion('已保存第一项，第二项还未保存。' if self.calls == 3 else '两项工作均已保存。',
                                business=True, operation_ids=receipts, task={'state': 'blocked', 'remaining': ['第二项还未保存']} if self.calls == 3 else {'state': 'completed'})
        return ChatResult(generations=[ChatGeneration(message=result)])


async def test_partial_business_completion_keeps_receipt_without_a_judge_reopening_the_graph(setup):
    fake = ProtocolThenActionModel(model='controlled', api_key='unused')
    result, stored = await run(setup, fake, '创建工作1和工作2')
    assert fake.calls == 3 and fake.reviews == 0
    assert not stored.get('deliveryRepairs')
    assert len(result['actions']) == 1 and result['actions'][0]['state'] == 'succeeded'
    works = (await setup[3]['employee'].get('/api/v1/work-items')).json()['items']
    assert len(works) == 1 and works[0]['title'] == '工作1' and works[0]['revision'] == 1
    assert result['job']['taskOutcome']['state'] == 'partial'
    assert '第二项还未保存' in result['reply']


async def test_protocol_and_semantic_repairs_have_separate_persistent_budgets(setup):
    from app.agent.completion.delivery import take_repair
    from _support.agent.business_actions import runtime
    context, _ = await runtime(setup)
    assert await take_repair(context, 'protocol')
    assert not await take_repair(context, 'protocol')
    assert await take_repair(context, 'response')
    assert not await take_repair(context, 'action')
    assert not await take_repair(context, 'response')
    assert await take_repair(context, 'response', resume=True)
    async with context.sessions() as db:
        assert (await db.get(Job, context.job_id)).result['deliveryRepairs'] == ['protocol', 'response']


@pytest.mark.parametrize('reject', [False, True])
async def test_required_tool_choice_has_one_explicit_unsupported_fallback(monkeypatch, reject):
    import httpx
    from types import SimpleNamespace
    from app.integrations.models.chat import chat
    from _support.agent.model_stream_errors import client_for, stream
    from _support.agent.fakes import wire_completion
    calls, timing = [], []
    def response(request):
        payload = json.loads(request.content)
        calls.append(payload)
        if reject and len(calls) == 1:
            return httpx.Response(400, json={'error': {'message': 'tool_choice required is not supported', 'code': 'invalid_parameter'}})
        arguments = wire_completion('正常单次正文')['tool_calls'][0]['function']['arguments']
        return stream({'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'c', 'function': {'name': 'finish_task', 'arguments': arguments}}]}, 'finish_reason': 'tool_calls'}]})
    client_for(monkeypatch, response)
    result = await chat(SimpleNamespace(model_allowed_origins=()), {'baseUrl': 'https://example.org/v1', 'model': 'controlled', 'streaming': True}, 'unused',
                        [{'role': 'user', 'content': '解释概念'}], tools=[{'type': 'function', 'function': {'name': 'finish_task'}}], tool_choice='required',
                        on_timing=lambda event, **fields: timing.append((event, fields)))
    assert len(calls) == 1 + int(reject)
    assert calls[0]['tool_choice'] == 'required'
    if reject:
        assert calls[1]['tool_choice'] == 'auto'
        assert any(event == 'model.compatibility' for event, _ in timing)
    assert result['choices'][0]['message']['tool_calls'][0]['function']['name'] == 'finish_task'


@pytest.mark.parametrize('malicious_retry', [False, True])
async def test_legacy_prose_recovery_keeps_unfinished_state_and_never_replays_tools(setup, malicious_retry):
    class Recovering(DeliveryModel):
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            self.calls += 1
            if self.calls == 1:
                reply = completion('已读第一份材料，另一份尚不可用。', operation_ids=['invalid-receipt'],
                                   task={'state': 'blocked', 'remaining': ['另一份材料不可用']})
            else:
                assert not kwargs.get('tools') and kwargs.get('tool_choice') in (None, 'none')
                assert 'task 填' not in messages[0].text and 'answer_length' not in messages[0].text
                reply = AIMessage(content='已读第一份材料，另一份尚不可用。')
                if malicious_retry:
                    reply = completion('不应被接受的操作声明')
                    reply.tool_calls.append({'name': 'execute_business_action', 'id': 'forbidden-write',
                                             'args': {'step': 1, 'action': 'create_work', 'changes': {'title': '不能创建'}}})
            return ChatResult(generations=[ChatGeneration(message=reply)])
    fake = Recovering(model='controlled', api_key='unused')
    result, stored = await run(setup, fake, '分析两份材料')
    assert fake.calls == 2 and stored['deliveryRepairs'] == ['protocol']
    assert not result['actions']
    assert (await setup[3]['employee'].get('/api/v1/work-items')).json()['items'] == []
    if malicious_retry:
        assert result['job']['state'] == 'failed' and '不应被接受' not in result['reply']
    else:
        assert result['reply'] == '已读第一份材料，另一份尚不可用。'
        assert result['job']['taskOutcome']['state'] == 'blocked'
        assert result['job']['taskOutcome']['remaining'] == ['另一份材料不可用']
        assert stored['incompleteTask']


@pytest.mark.parametrize('marker,prior_repair', [
    ('delivery-repair', False), ('delivery-references', False), ('delivery-references', True),
])
async def test_legacy_repair_checkpoint_preserves_only_unfinished_state(setup, monkeypatch, marker, prior_repair):
    from types import SimpleNamespace

    class CompletedGraph:
        def __init__(self, context):
            self.context = context

        async def aget_state(self, config):
            context = self.context
            pending = completion('第一份已处理，第二份尚不可用。', operation_ids=['invalid-receipt'],
                                 task={'state': 'blocked', 'remaining': ['第二份材料不可用'],
                                       'directiveChange': 'replace', 'directiveQuote': '未经核对的授权',
                                       'directiveScope': '允许自动修改所有工作'})
            messages = [HumanMessage(id='job:' + context.job_id, content='分析两份材料')]
            if prior_repair:
                messages.extend([AIMessage(content='第一份已处理，第二份尚不可用。'),
                                 HumanMessage(id='delivery-repair:' + context.job_id, content='历史格式修复')])
            messages.extend([
                pending,
                ToolMessage(tool_call_id=pending.tool_calls[0]['id'], name='finish_task',
                            content='无效回执', status='error'),
                HumanMessage(id=marker + ':' + context.job_id, content='历史答复修复'),
                AIMessage(content='第一份已处理，第二份尚不可用。'),
            ])
            return SimpleNamespace(next=(), values={'messages': messages})

    monkeypatch.setattr('app.agent.harness.build_graph', lambda settings, saver, context, model: CompletedGraph(context))
    fake = model()
    result, stored = await run(setup, fake, '分析两份材料')
    assert fake.calls == 0 and not stored.get('deliveryRepairs')
    assert result['reply'] == '第一份已处理，第二份尚不可用。'
    assert result['job']['taskOutcome']['state'] == 'blocked'
    assert result['job']['taskOutcome']['remaining'] == ['第二份材料不可用']
    assert stored['incompleteTask']
    assert stored['taskInterpretation']['directiveChange'] == 'keep'
    assert not stored['taskInterpretation']['directiveQuote'] and not stored['taskInterpretation']['directiveScope']
    assert not result['actions'] and not stored.get('toolOutcomes')
