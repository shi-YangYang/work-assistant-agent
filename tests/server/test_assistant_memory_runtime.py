import json
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, messages_to_dict
from langgraph.checkpoint.memory import InMemorySaver
from app.agent.memory.middleware import request_memory, without_memory, validate_completed
from app.agent.context.context_usage import estimate_request, input_budget
from app.agent.harness import invoke_harness
from app.modules.memories import service
from app.modules.messages.models import Message
from app.tasks.context import RunContext
from app.tasks.models import Job
from app.tasks.runtime.queue import claim
from test_assistant_memory import context_for, apply, PATH
from test_company import send
from fakes import controlled_model

pytestmark = pytest.mark.asyncio


async def test_injection_is_fresh_bounded_counts_tokens_and_never_persists(setup):
    client = setup[3]['employee']
    await client.put(PATH + '/document', json={'expectedRevision': 0, 'markdown': '# 交流偏好\n\n每次先给结论。\n\n' + '完整长段落。' * 300})
    context, _ = await context_for(setup, '解释版本控制')
    context.model_binding = {'assistant': {'contextCapability': {'inputLimit': 6000, 'contextWindow': 10000}}}
    original = [HumanMessage(id='job:' + context.job_id, content='解释版本控制')]
    messages, block = await request_memory(context, original, 4000)
    assert block and '先给结论' in block.text
    assert estimate_request([block]) - estimate_request([]) <= input_budget(context) * .1
    assert estimate_request([block, *messages]) > estimate_request(messages)
    # Changes apply to subsequent model requests without a memory cache.
    await client.patch(PATH + '/settings', json={'expectedRevision': 1, 'enabled': False})
    messages, block = await request_memory(context, [block, *messages], 4000)
    assert '先给结论' not in block.text and '已关闭' in block.text
    assert len(messages) == 1
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert '先给结论' not in json.dumps(job.result, ensure_ascii=False)


async def test_read_failure_never_uses_previous_memory(setup, monkeypatch):
    client = setup[3]['employee']
    await client.put(PATH + '/document', json={'expectedRevision': 0, 'markdown': '不可缓存的旧值'})
    context, _ = await context_for(setup)
    messages = [HumanMessage(id='user', content='当前输入')]
    _, old = await request_memory(context, messages, 4000)
    assert old
    async def fail(*args, **kwargs):
        raise ConnectionError('controlled read failure')
    monkeypatch.setattr(service, 'read', fail)
    clean, block = await request_memory(context, [old, *messages], 4000)
    assert block is None and len(clean) == 1


@pytest.mark.parametrize('tool_name', ['save_memory', None])
async def test_memory_tool_payloads_removed_from_summary_and_old_success_revalidated(setup, tool_name):
    context, _ = await context_for(setup)
    receipt = await apply(context, evidence='以后先给结论，少用表格', new='只在记忆出现的内容')
    messages = [HumanMessage(id='user', content='用户原文保留'),
        AIMessage(id='call', content='', tool_calls=[{'id':'save1','name':'save_memory','args':{'new_text':'只在记忆出现的内容'}}]),
        ToolMessage(id='tool', name=tool_name, tool_call_id='save1', content=json.dumps(receipt))]
    clean, _ = await request_memory(context, messages, 4000)
    assert json.loads(clean[-1].content)['state'] == 'succeeded'
    assert clean[-2].tool_calls == messages[-2].tool_calls
    summary = without_memory(clean, summaries=True)
    assert '只在记忆出现的内容' not in json.dumps(messages_to_dict(summary), ensure_ascii=False)
    assert summary == [messages[0]]
    await setup[3]['employee'].delete(PATH + '/document?expectedRevision=1')
    clean, _ = await request_memory(context, messages, 4000)
    assert json.loads(clean[-1].content)['state'] == 'conflict'
    assert clean[-2].tool_calls[0]['args'] == {}
    with pytest.raises(ValueError, match='旧任务结果已失效'):
        await validate_completed(context)


async def test_real_graph_checkpoint_does_not_contain_ephemeral_memory(setup):
    client = setup[3]['employee']
    await client.put(PATH + '/document', json={'expectedRevision': 0, 'markdown': '特殊私密背景 MEMORY-NOT-IN-CHECKPOINT'})
    context, _ = await context_for(setup, '普通提问')
    model = controlled_model('clarify')
    saver = InMemorySaver()
    await invoke_harness(context, saver, '普通提问', model)
    checkpoints = json.dumps(saver.storage, default=str, ensure_ascii=False)
    assert 'MEMORY-NOT-IN-CHECKPOINT' not in checkpoints
    assert not context.memory_snapshot is None
