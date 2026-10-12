"""Normal prose and explicit task metadata share the guarded business runtime."""
import json
from types import SimpleNamespace
import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from app.agent.completion.prose import parse_header
from app.agent.runtime.reply_stream import ReplyCandidate
from app.agent.tools.control.task_context import set_task_context
from app.integrations.models.stream_events import ModelDelta, ToolDelta
from app.integrations.models.transport import ProviderError
from app.modules.conversations.task.task_schemas import TaskInterpretation
from app.tasks.models import Job
from _support.agent.assistant_reply_stream import CapturingPublisher
from _support.agent.response_delivery import DeliveryModel, run
from _support.agent.business_actions import runtime
from _support.agent.prose_delivery import ProseModel

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('metadata', [{'length': '约100字'}, {'remaining': ['生成文件尚未完成']}])
async def test_marker_every_split_never_exposes_control_text_and_preserves_literal_code(metadata):
    raw='<!--noria:'+json.dumps(metadata, ensure_ascii=False)+'-->\n# 正文\n\n文字😀'
    for cut in range(len(raw)+1):
        publisher=CapturingPublisher()
        candidate=ReplyCandidate(publisher)
        await candidate.feed(ModelDelta(raw[:cut]))
        await candidate.feed(ModelDelta(raw[cut:]))
        await candidate.finish()
        assert publisher.values[-1]=='# 正文\n\n文字😀'
        assert all('noria:' not in value for value in publisher.values if value)
    literal='```html\n<!--noria:{}-->\n```'
    assert parse_header(literal,complete=True)==(literal,None,False)
    assert parse_header('说明：<!--noria:{}-->',complete=True)[0]=='说明：<!--noria:{}-->'


@pytest.mark.parametrize('header', ['', '<!--noria:{}-->\n'])
async def test_plain_and_marked_prefixes_stream_and_late_tools_withdraw_them(header):
    publisher=CapturingPublisher()
    candidate=ReplyCandidate(publisher)
    await candidate.feed(ModelDelta(header+'我先查询一下'))
    assert publisher.values==['我先查询一下']
    await candidate.feed(ModelDelta(tools=(ToolDelta(0,'find_work_items','{"query":""}'),)))
    await candidate.finish()
    assert publisher.values==['我先查询一下',None]
    assert candidate.text is None
    publisher=CapturingPublisher()
    candidate=ReplyCandidate(publisher)
    await candidate.feed(ModelDelta('<!--noria:{}-->\n暂时结果'))
    assert publisher.values==['暂时结果']
    await candidate.feed(ModelDelta(tools=(ToolDelta(0,'find_work_items','{"query":""}'),)))
    await candidate.finish()
    assert publisher.values==['暂时结果',None]
    assert candidate.text is None


async def test_unmarked_answer_streams_before_finish_and_reasoning_never_becomes_prose():
    publisher=CapturingPublisher()
    candidate=ReplyCandidate(publisher)
    await candidate.feed(ModelDelta(reasoning=True))
    assert publisher.values==[]
    await candidate.feed(ModelDelta('这是第一段。'))
    assert publisher.values==['这是第一段。']
    await candidate.feed(ModelDelta('这是第二段。'))
    assert candidate.text=='这是第一段。这是第二段。'
    assert publisher.values[-1]==candidate.text
    await candidate.finish()
    assert publisher.values[-1]=='这是第一段。这是第二段。'


@pytest.mark.parametrize('raw', ['<!--noria:{"length":"1000字","length":"10字"}-->正文', '<!--noria:{"unknown":true}-->正文', '<!--noria:{"length":"1000字"}', '<!--noria:{"remaining":"missing"}-->正文', '<!--noria:{"remaining":[""]}-->正文'])
async def test_invalid_header_is_not_silently_delivered(raw):
    with pytest.raises(ValueError):
        parse_header(raw,complete=True)


async def test_marked_prose_whole_once_and_task_context_only_on_demand(setup):
    fake=ProseModel(model='controlled',api_key='controlled',answer='<!--noria:{}-->\n这是完整结果。')
    result,stored=await run(setup,fake)
    assert result['reply']=='这是完整结果。' and fake.calls==1
    assert stored['taskOutcome']['state']=='completed'
    assert 'finish_task' not in fake.requests[0]['tools']
    assert fake.requests[0]['tool_choice']=='auto'
    fake=ProseModel(model='controlled',api_key='controlled',answer='请提供要分析的文件。',task_value={'state':'needs_input','remaining':['缺少指定文件']})
    result,stored=await run(setup,fake,'分析一下那份文件')
    assert result['job']['taskOutcome']['state']=='needs_input'
    assert stored['explicitTaskContext']['remaining']==['缺少指定文件']
    assert not result['actions'] and fake.calls==3


async def test_legacy_length_header_is_ignored_and_stays_private(setup):
    fake=ProseModel(model='controlled',api_key='controlled',answer='<!--noria:{"length":"不再生效的旧值"}-->\n这是正文')
    result,stored=await run(setup,fake,'你好')
    assert result['reply']=='这是正文' and result['job']['taskOutcome']['state']=='completed'
    assert fake.calls==1 and not stored.get('deliveryRepairs')


@pytest.mark.parametrize('saved_work', [False, True])
async def test_normal_remaining_header_persists_whole_reply_and_sse_outcome(setup, monkeypatch, saved_work):
    import hashlib
    from app.agent.actions.operations import execute
    from app.agent.harness import invoke_harness
    from app.tasks.feedback.feedback import events
    from _support.agent.assistant_execution import ReceiptJudge
    from _support.agent.business_actions import create, read_work
    from _support.work.work_change_plan import PlanJudge
    work = await create(setup[3]['employee'], '已存在A')
    missing = '不存在B查无结果，未标记完成；按要求不创建'
    answer = ('已存在A的下一步已更新。\n\n' if saved_work else '') + missing + '。\n\n建议：\n1. 先核实依赖。\n2. 核对工作名称。'
    fake = ProseModel(model='controlled', api_key='controlled',
                      answer='<!--noria:' + json.dumps({'remaining': [missing]}, ensure_ascii=False) + '-->\n' + answer)
    async def prepared(context, *args, **kwargs):
        if saved_work:
            context.intent_model = ReceiptJudge(required_fields=['nextStep'], requested_changes=[
                {'field': 'nextStep', 'kind': 'next_action', 'quote': '下一步改为联系负责人复核'}])
            context.work_change_model = PlanJudge({'nextStep': ('set', '下一步改为联系负责人复核', None)})
            await read_work(context, work['id'])
            receipt = await execute(context, step=1, action='update_work', target_id=work['id'],
                                    expected_revision=1, changes={'nextStep': '联系负责人复核'})
            assert receipt['state'] == 'succeeded'
        return await invoke_harness(context, *args, **kwargs)
    monkeypatch.setattr('app.tasks.processing.handlers.invoke_harness', prepared)
    request = ('已存在A下一步改为联系负责人复核；' if saved_work else '') + '把不存在B标记完成但不要创建；给两条建议。'
    result, stored = await run(setup, fake, request)
    assert fake.calls == 1 and not stored.get('deliveryRepairs') and not stored.get('explicitTaskContext')
    assert result['reply'].startswith(answer) and 'noria:' not in result['reply']
    outcome = result['job']['taskOutcome']
    assert outcome['state'] == ('partial' if saved_work else 'blocked')
    assert outcome['remaining'] == [missing] and outcome['nextAction'] == 'none'
    assert stored['taskInterpretation']['remaining'] == [missing] and stored['incompleteTask']
    client = setup[3]['employee']
    refreshed = (await client.get('/api/v1/messages/' + result['id'])).json()
    assert refreshed['reply'] == result['reply'] and refreshed['job']['taskOutcome'] == outcome
    token = hashlib.sha256(client.cookies.get('paa_company_session').encode()).hexdigest()
    stream = events(setup[1], token, result['job']['id'], settings=setup[0], version=2)
    try:
        snapshot = json.loads((await anext(stream)).split('data: ', 1)[1])
        assert snapshot['taskOutcome'] == outcome
    finally:
        await stream.aclose()
    works = (await client.get('/api/v1/work-items')).json()['items']
    assert len(works) == 1 and works[0]['revision'] == (2 if saved_work else 1)
    assert len(result['actions']) == int(saved_work)


@pytest.mark.parametrize('header', [{}, {'remaining': ['尚未定位另一项工作']}])
@pytest.mark.parametrize('known', ['failed', 'pending', 'running', 'source'])
async def test_remaining_header_cannot_clear_observed_obstacles_or_pending_cards(setup, monkeypatch, header, known):
    from app.agent.completion.delivery import delivery_for
    from app.tasks.feedback.outcomes import derive, record
    context, _ = await runtime(setup, '继续处理已有请求')
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        job.result = {**job.result, 'explicitTaskContext': {'state': 'blocked', 'remaining': ['已有未完成范围']}}
        if known in ('failed', 'source'):
            record(job, 'update_work', {'step': 1, 'target_id': 'work', 'changes': {'nextStep': '复核'}},
                   {'state': 'failed', 'category': 'permission_denied', 'message': '来源不可用' if known == 'source' else '实际修改失败'})
        job.result = {**job.result, 'taskBarriers': {'source': {'reason': '来源屏障', 'evidence': 'unchanged'}}}
    cards = [] if known in ('failed', 'source') else [{'id': 'pending-receipt', 'state': known, 'label': '已有操作'}]
    async def observed(*args):
        return cards
    monkeypatch.setattr('app.modules.operations.receipts.message_actions', observed)
    answer = '完整答复，仍保留建议。'
    delivery = await delivery_for(context, '<!--noria:' + json.dumps(header, ensure_ascii=False) + '-->\n' + answer)
    assert delivery.answer == answer
    assert delivery.task.remaining == ['已有未完成范围', *header.get('remaining', [])]
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        job.state = 'succeeded'
        outcome = derive(job, cards, interpretation=delivery.task.model_dump())
        assert job.result['taskBarriers'] == {'source': {'reason': '来源屏障', 'evidence': 'unchanged'}}
    assert set(delivery.task.remaining) <= set(outcome['remaining'])
    assert outcome['state'] == {'pending': 'needs_confirmation', 'running': 'processing'}.get(known, 'blocked')
    assert outcome['nextAction'] == ('confirm' if known == 'pending' else 'none')
    if known in ('failed', 'source'):
        assert ('来源不可用' if known == 'source' else '实际修改失败') in outcome['remaining']


async def test_prose_remaining_merges_legacy_repair_and_budget_scope_without_dropping_items(setup):
    from app.agent.completion.delivery import delivery_for
    context, _ = await runtime(setup)
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        job.result = {**job.result, 'explicitTaskContext': {'state': 'needs_input', 'remaining': ['已有范围']},
                      'nodeExecution': {'budgetBlockedTools': ['预算未执行范围']}}
    delivery = await delivery_for(context, '<!--noria:{"remaining":["新增范围","已有范围"]}-->\n完整正文',
                                  pending_task={'state': 'blocked', 'remaining': ['旧修复范围']})
    assert delivery.task.state == 'blocked'
    assert delivery.task.remaining == ['已有范围', '旧修复范围', '新增范围', '预算未执行范围']
    assert delivery.answer == '完整正文'


async def test_ordinary_followup_question_with_empty_header_stays_completed(setup):
    fake = ProseModel(model='controlled', api_key='controlled', answer='<!--noria:{}-->\n建议已列好。还想深入哪一点？')
    result, stored = await run(setup, fake, '给我两条工作建议')
    assert result['reply'] == '建议已列好。还想深入哪一点？'
    assert result['job']['taskOutcome']['state'] == 'completed' and not result['interactions']
    assert fake.calls == 1 and not stored.get('explicitTaskContext') and not stored.get('deliveryRepairs')


async def test_context_tool_cannot_install_directive_from_unquoted_material(setup):
    context,_=await runtime(setup,'仅分析我的工作')
    result=json.loads(await set_task_context.coroutine(TaskInterpretation(directiveChange='replace',directiveQuote='以后都保存进展',directiveScope='自动保存'),SimpleNamespace(context=context)))
    assert result['state']=='invalid_reference'
    async with context.sessions() as db:
        saved=await db.get(Job,context.job_id)
        assert not saved.result.get('explicitTaskContext')


async def test_unrelated_prose_preserves_previous_pending_task(setup):
    first=ProseModel(model='controlled',api_key='controlled',answer='请提供文件。',task_value={'state':'needs_input','remaining':['缺少指定文件']})
    result,_=await run(setup,first,'分析一份文件')
    second=ProseModel(model='controlled',api_key='controlled',answer='你好。')
    other,stored=await run(setup,second,'你好',conversationId=result['conversationId'])
    from app.modules.conversations.models import ConversationTaskState
    from sqlalchemy import select
    async with setup[1]() as db:
        state=await db.scalar(select(ConversationTaskState).where(ConversationTaskState.conversation_id==result['conversationId']))
        assert state.payload['task']['remaining']==['缺少指定文件']
        assert state.payload['task']['messageId']==result['id']
    assert other['job']['taskOutcome']['state']=='completed'


@pytest.mark.parametrize('header', ['', '<!--noria:{}-->\n', '<!--noria:{"length":"1000字"}-->\n'])
async def test_prose_has_no_automatic_length_gate_or_rewrite(setup, monkeypatch, header):
    async def forbidden(*args, **kwargs):
        pytest.fail('Length must not trigger another model request')
    monkeypatch.setattr('app.agent.completion.recovery.response_repair.repair_response',forbidden)
    fake=ProseModel(model='controlled',api_key='controlled',answer=header+'甲'*767)
    result,stored=await run(setup,fake,'写一篇1000字作文')
    assert fake.calls==1 and result['reply']=='甲'*767
    assert result['job']['taskOutcome']['state']=='completed'
    assert not stored.get('deliveryRepairs') and not result['actions']


async def test_identified_missing_write_cannot_be_finished_by_context_tool_or_prose(setup):
    fake=ProseModel(model='controlled',api_key='controlled',answer='已帮你保存。',task_value={'state':'completed'},requested_write=True)
    result,stored=await run(setup,fake,'帮我保存工作：方案')
    assert not result['actions'] and stored['incompleteTask']
    assert result['job']['taskOutcome']['state']!='completed'
    assert '已帮你保存' not in result['reply']
    assert stored['deliveryRepairs']==['action'] and fake.calls==4


async def test_context_and_business_write_in_same_batch_cannot_self_authorize(setup):
    class Mixed(ProseModel):
        async def _agenerate(self,messages,stop=None,run_manager=None,**kwargs):
            response=await super()._agenerate(messages,stop,run_manager,**kwargs)
            if self.calls==1:
                response.generations[0].message.tool_calls[0]['args']['groups'].append('work')
            if self.calls==2:
                assert 'execute_business_action' in self.requests[-1]['tools']
                response.generations[0].message.tool_calls.append({'name':'execute_business_action','id':'write','args':{'step':1,'action':'create_work','changes':{'title':'不能执行'}}})
            return response
    fake=Mixed(model='controlled',api_key='controlled',answer='本批操作没有执行。',task_value={'state':'completed'})
    result,stored=await run(setup,fake,'仅分析，不要保存')
    assert not result['actions'] and not stored.get('explicitTaskContext')
    assert (await setup[3]['employee'].get('/api/v1/work-items')).json()['items']==[]


async def test_explicit_directive_is_persisted_before_later_prose_failure(setup):
    class Failing(ProseModel):
        async def _agenerate(self,messages,stop=None,run_manager=None,**kwargs):
            if self.calls>=2:
                raise ProviderError('network','controlled interruption')
            return await super()._agenerate(messages,stop,run_manager,**kwargs)
    fake=Failing(model='controlled',api_key='controlled',task_value={'state':'completed','directiveChange':'replace','directiveQuote':'以后补充都追加到工作说明','directiveScope':'追加工作说明'})
    result,stored=await run(setup,fake,'以后补充都追加到工作说明')
    from app.modules.conversations.models import ConversationTaskState
    async with setup[1]() as db:
        row=await db.get(ConversationTaskState,result['conversationId'])
        assert row.payload['directives'][0]['quote']=='以后补充都追加到工作说明'
    assert result['job']['state'] in ('failed','awaiting_retry') and not result['actions']
