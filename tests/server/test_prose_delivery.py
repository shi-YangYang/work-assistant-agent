"""Normal prose and explicit task metadata share the guarded business runtime."""
import json
from types import SimpleNamespace
import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from app.agent.completion.prose import parse_header
from app.agent.runtime.reply_stream import ReplyCandidate
from app.agent.tools.task_context import set_task_context
from app.integrations.models.stream_events import ModelDelta, ToolDelta
from app.integrations.models.transport import ProviderError
from app.modules.conversations.task.task_schemas import TaskInterpretation
from app.tasks.models import Job
from test_assistant_reply_stream import CapturingPublisher
from test_response_delivery import DeliveryModel, run
from test_business_actions import runtime

pytestmark = pytest.mark.asyncio


async def test_marker_every_split_never_exposes_control_text_and_preserves_literal_code():
    raw='<!--noria:{"length":"约100字"}-->\n# 正文\n\n文字😀'
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


@pytest.mark.parametrize('raw', ['<!--noria:{"length":"1000字","length":"10字"}-->正文', '<!--noria:{"unknown":true}-->正文', '<!--noria:{"length":"1000字"}'])
async def test_invalid_header_is_not_silently_delivered(raw):
    with pytest.raises(ValueError):
        parse_header(raw,complete=True)


class ProseModel(DeliveryModel):
    task_value: dict | None = None
    requested_write: bool = False
    async def _agenerate(self,messages,stop=None,run_manager=None,**kwargs):
        self.calls+=1
        self.requests.append({'tools':[tool['function']['name'] for tool in kwargs.get('tools',[])],'tool_choice':kwargs.get('tool_choice')})
        if self.task_value and self.calls==1:
            assert self.requests[-1]['tools']==['load_tools']
            result=AIMessage(content='',tool_calls=[{'name':'load_tools','id':'load-context','args':{'groups':['task_context']}}])
        elif self.task_value and self.calls==2:
            assert 'set_task_context' in self.requests[-1]['tools']
            result=AIMessage(content='',tool_calls=[{'name':'set_task_context','id':'task-context','args':{'task':self.task_value,'business_requested':self.requested_write}}])
        else:
            result=AIMessage(content=self.answer)
        return ChatResult(generations=[ChatGeneration(message=result)])


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
    monkeypatch.setattr('app.agent.completion.response_repair.repair_response',forbidden)
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
