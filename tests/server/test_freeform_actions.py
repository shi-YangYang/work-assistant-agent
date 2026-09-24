"""Regressions from open-ended conversations, with deterministic boundaries."""
import httpx
import json
import pytest
from langchain_core.messages import AIMessage
from paa_server.agent.intent import authorize_intent
from paa_server.agent.middleware import ToolBoundary
from paa_server.agent.operations import execute
from paa_server.agent.reply_review import check_segments, reply_segments
from paa_server.modules.reports.models import Report
from paa_server.modules.work.models import WorkRevision
from paa_server.tasks.models import Job
from sqlalchemy import select
from test_business_actions import Judge, create, read_work, run_reply, runtime
from types import SimpleNamespace
from unittest.mock import AsyncMock



pytestmark = pytest.mark.asyncio


async def test_query_in_parallel_write_batch_is_deferred_until_next_model_step(setup):
    context, _ = await runtime(setup, '修改后列出当前工作')
    read = {'id': 'query', 'name': 'find_work_items', 'args': {}}
    write = {'id': 'write', 'name': 'execute_business_action', 'args': {'action': 'update_work'}}
    request = SimpleNamespace(runtime=SimpleNamespace(context=context), tool_call=read, state={'messages': [AIMessage(content='', tool_calls=[write, read])]})
    handler = AsyncMock(return_value='fresh-result')
    result = await ToolBoundary().awrap_tool_call(request, handler)
    assert 'error' in json.loads(result.content)
    handler.assert_not_awaited()
    request.state['messages'].append(AIMessage(content='', tool_calls=[read]))
    assert await ToolBoundary().awrap_tool_call(request, handler) == 'fresh-result'
    handler.assert_awaited_once()


async def test_business_planning_default_preserves_explicit_reasoning_and_unknown_providers():
    from paa_server.modules.model_services.parameters import business_model_config
    config = {'baseUrl': 'https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1', 'model': 'deepseek-v4.1-flash', 'parameters': {'temperature': .2}}
    assert business_model_config(config, {})['parameters'] == {'temperature': .2, 'enable_thinking': True, 'reasoning_effort': 'low'}
    assert config['parameters'] == {'temperature': .2}
    assert business_model_config(config, {'presetId': 'chosen'}) is config
    for key, value in [('enable_thinking', True), ('thinking', {'type': 'enabled'}), ('thinking_budget', 2048), ('reasoning_effort', 'high')]:
        explicit = {**config, 'parameters': {key: value}}
        assert business_model_config(explicit, {}) is explicit
    for changed in [{'baseUrl': 'https://custom.example/v1'}, {'model': 'unknown-model'}]:
        unknown = {**config, **changed}
        assert business_model_config(unknown, {}) is unknown


def verdict(kinds, proof=()):
    return json.dumps({'segments': [{'index': i, 'kind': kind, 'evidence': list(proof) if kind == 'query_fact' else []} for i, kind in enumerate(kinds)]})


async def test_numbered_list_and_its_count_are_an_atomic_review_block():
    answer = '目前有三项：\n1. 名单已改回进行中。\n2. 脚本仍在准备。\n3. 反馈收集有阻碍。\n\n需要讨论哪部分？'
    parts = reply_segments(answer)
    assert len(parts) == 2
    assert parts[0].startswith('目前有三项：\n1. ') and '3. 反馈' in parts[0]
    removed = check_segments(parts, verdict(['execution', 'information']), [])
    assert removed.text == '需要讨论哪部分？'
    evidence = [{'id': 42, 'tool': 'find_work_items', 'result': '{"items":[]}'}]
    kept = check_segments(parts, verdict(['query_fact', 'information'], [42]), evidence)
    assert kept.text == answer


async def test_table_introduction_and_orphan_heading_are_removed_together():
    parts = reply_segments('本轮修改：\n\n| 字段 | 值 |\n|---|---|\n| 标题 | 测试 |\n\n可以继续补充。')
    assert len(parts) == 2 and parts[0].startswith('本轮修改：')
    assert check_segments(parts, verdict(['execution', 'information']), []).text == '可以继续补充。'
    parts = reply_segments('## 修改结果\n\n已更新工作。\n\n## 建议\n\n建议先确认参与人。')
    assert len(parts) == 4
    assert check_segments(parts, verdict(['information', 'execution', 'information', 'information']), []).text == '## 建议\n\n建议先确认参与人。'


@pytest.mark.parametrize('proof', [[], [999], [8]])
async def test_invalid_query_proof_is_dropped_without_retaining_false_claim(proof):
    evidence = [{'id': 8, 'tool': 'execute_business_action', 'result': '{"state":"pending"}'}]
    result = check_segments(['报告已经提交。', '要查看哪一天？'], verdict(['query_fact', 'information'], proof), evidence)
    assert result.verified and result.text == '要查看哪一天？'
    with pytest.raises(ValueError):
        check_segments(['a', 'b'], '{"segments":[{"index":0,"kind":"information"},{"index":0,"kind":"information"}]}', [])


async def test_current_fields_can_use_saved_snapshot_but_not_pending_or_execution_claims():
    snapshot = {'state': 'succeeded', 'objectId': 'work-a', 'objectRevision': 2, 'details': {'title': '反馈', 'status': 'blocked'}}
    evidence = [{'id': 8, 'tool': 'execute_business_action', 'result': json.dumps(snapshot)}]
    parts = ['当前未完成：\n1. 反馈：有阻碍。', '已帮你修改。']
    result = check_segments(parts, verdict(['query_fact', 'execution'], [8]), evidence)
    assert result.text == parts[0]
    for invalid in [{**snapshot, 'state': 'pending'}, {'state': 'succeeded'}]:
        evidence[0]['result'] = json.dumps(invalid)
        assert check_segments(parts, verdict(['query_fact', 'execution'], [8]), evidence).text == ''


async def test_equivalent_success_resolves_old_feedback_even_if_model_changes_step(setup):
    _, _, _, c = setup
    work = await create(c['employee'])
    context, sent = await runtime(setup, '完成这项工作，并修改标题', allowed=False)
    await read_work(context, work['id'])
    args = {'action': 'update_work', 'target_id': work['id'], 'expected_revision': 1, 'changes': {'status': 'done'}}
    await execute(context, step=1, **args)
    await execute(context, step=2, **{**args, 'changes': {'title': '新标题'}})
    context.intent_model = Judge()
    assert (await execute(context, step=3, **args))['state'] == 'succeeded'
    detail = (await c['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert [item['step'] for item in detail['job']['operationFeedback']] == [2]
    assert len(detail['actions']) == 1


async def test_incomplete_intent_model_response_is_not_reported_as_bad_user_fields(setup):
    from paa_server.agent.intent import IntentCheckFailed
    from paa_server.integrations.models.transport import ProviderError
    _, _, _, c = setup
    work = await create(c['employee'])
    context, sent = await runtime(setup, '完成这项工作')
    await read_work(context, work['id'])
    context.intent_model = SimpleNamespace(ainvoke=AsyncMock(side_effect=ProviderError('invalid_response', '模型响应未正常完成或达到输出限制')))
    with pytest.raises(IntentCheckFailed, match='模型未返回完整有效结果'):
        await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=1, changes={'status': 'done'})
    detail = (await c['employee'].get('/api/v1/messages/' + sent['messageId'])).json()
    assert detail['job']['operationFeedback'] == [] and detail['actions'] == []
    assert (await c['employee'].get('/api/v1/work-items/' + work['id'])).json()['status'] == 'in_progress'


@pytest.mark.parametrize('mode', ['repair', 'still_missing', 'already_saved', 'rejected'])
async def test_missing_operation_repairs_once_without_replaying_saved_or_rejected_writes(setup, monkeypatch, mode):
    calls = []
    async def graph(context, saver, content, model, **options):
        calls.append(options)
        context.intent_model = Judge()
        if mode == 'repair' and options.get('repair_missing_action'):
            await execute(context, step=1, action='create_work', changes={'title': '只补建一次'})
        return '已创建工作。'
    class CompletionJudge:
        async def ainvoke(self, messages):
            return AIMessage(content='{"segments":[{"index":0,"kind":"execution","evidence":[]}],"needs_action":true}')
    async def before(context):
        context.intent_model = Judge(mode != 'rejected')
        await execute(context, step=1, action='create_work', changes={'title': '已有一次操作'})
    monkeypatch.setattr('paa_server.tasks.handlers.invoke_harness', graph)
    data = await run_reply(setup, '帮我创建一项工作', '', CompletionJudge(), before=before if mode in ('already_saved', 'rejected') else None)
    assert len(calls) == (1 if mode in ('already_saved', 'rejected') else 2)
    if len(calls) == 2:
        assert calls[1] == {'repair_missing_action': True}
    assert len(data['actions']) == (1 if mode in ('repair', 'already_saved') else 0)
    if not data['actions']:
        assert '未执行' in data['reply']


async def test_report_rewrite_judge_gets_original_facts_and_cannot_save_rejected_milestone(setup):
    from paa_server.agent.tools.actions import query_reports
    _, sessions, users, c = setup
    work = await create(c['employee'], title='试用初稿', nextStep='拟出初稿并发出内部确认')
    async with sessions.begin() as db:
        source = await db.scalar(select(WorkRevision).where(WorkRevision.work_id == work['id']))
        other = await create(c['peer'], title='不应进入核对器的他人工作')
        other_source = await db.scalar(select(WorkRevision).where(WorkRevision.work_id == other['id']))
        report = Report(company_id=users['employee'].company_id, owner_id=users['employee'].id, kind='daily', period='2026-09-20', period_end='2026-09-20', timezone='Asia/Shanghai', content={'completed': '', 'ongoing': '试用初稿待准备', 'blockers': '', 'next': '拟出初稿并发出内部确认'}, source_ids=[source.id, other_source.id])
        db.add(report); await db.flush()
    context, _ = await runtime(setup, '把日报改成老板看得懂的简短版本，不要夸大成果')
    data = json.loads(await query_reports.coroutine(SimpleNamespace(context=context), report_id=report.id))
    assert data['items'][0]['sourceFacts']['items'] == [{'id': source.id, 'content': source.content}]
    class FactJudge(Judge):
        async def ainvoke(self, messages):
            payload = json.loads(messages[-1].content)
            assert '不应进入核对器' not in json.dumps(payload, ensure_ascii=False)
            if payload.get('task') == 'report_fact_review':
                assert payload['confirmed'][0]['content']['nextStep'].startswith('拟出初稿')
                assert payload['userRequest'] == '把日报改成老板看得懂的简短版本，不要夸大成果'
                valid = '已拟出初稿' not in payload['report']['ongoing']
                return AIMessage(content=json.dumps({'valid': valid, 'reason': '' if valid else '计划不能改为已经完成的阶段'}))
            proposed = payload['proposedOperation']
            assert proposed['targetContent']['completed'] == ''
            assert proposed['reportSourceFacts']['items'][0]['content']['nextStep'].startswith('拟出初稿')
            # Permission to edit does not authorize invented progress.
            return AIMessage(content=json.dumps({'allowed': True, 'quote': payload['currentUserText'], 'reason': ''}))
    context.intent_model = FactJudge()
    denied = await execute(context, step=1, action='edit_report', target_id=report.id, expected_revision=1, changes={'ongoing': '已拟出初稿，待确认'})
    assert denied['state'] == 'clarification'
    assert '计划不能改为已经完成的阶段' in denied['message']
    unchanged = (await c['employee'].get('/api/v1/reports/' + report.id)).json()
    assert unchanged['revision'] == 1 and unchanged['content']['ongoing'] == '试用初稿待准备'
    corrected = await execute(context, step=1, action='edit_report', target_id=report.id, expected_revision=1, changes={'ongoing': '试用初稿待准备', 'next': '拟定初稿后发出确认'})
    assert corrected['state'] == 'succeeded'


async def test_delegated_candidate_only_prepares_confirmed_object_and_cancel_preserves_work(setup):
    _, _, _, c = setup
    work = await create(c['employee'])
    context, _ = await runtime(setup, '你挑一项不值得继续做的，给我确认删除对象')
    await read_work(context, work['id'])
    card = await execute(context, step=1, action='delete_work', target_id=work['id'], expected_revision=1)
    assert context.intent_model.inputs[0]['proposedOperation']['effect'] == 'prepare_confirmation'
    assert card['state'] == 'pending' and card['canConfirm']
    assert (await c['employee'].get('/api/v1/work-items/' + work['id'])).status_code == 200
    cancelled = await c['employee'].post(f"/api/v1/business-actions/{card['id']}/cancel", json={'expectedRevision': card['revision']})
    assert cancelled.json()['state'] == 'cancelled'
    assert (await c['employee'].get('/api/v1/work-items/' + work['id'])).status_code == 200


async def test_intent_judge_gets_actual_own_read_choices_without_stale_or_other_members(setup):
    from paa_server.agent.tools.work import find_work_items
    from paa_server.modules.work.models import WorkItem
    _, sessions, _, c = setup
    first = await create(c['employee'], title='准备名单')
    second = await create(c['employee'], title='整理结论')
    stale = await create(c['employee'], title='已经变化的工作')
    peer = await create(c['peer'], title='其他成员的工作')
    context, _ = await runtime(setup, '这几项里你挑一项，给我确认删除对象')
    await find_work_items.coroutine('', SimpleNamespace(context=context))
    context.read_versions[peer['id']] = peer['revision']
    async with sessions.begin() as db:
        row = await db.get(WorkItem, stale['id']); row.revision += 1
    card = await execute(context, step=1, action='delete_work', target_id=second['id'], expected_revision=1)
    request = context.intent_model.inputs[0]
    assert {w['id'] for w in request['verifiedReads']['ownWorkRead']} == {first['id'], second['id']}
    assert len(request['proposedOperation']['targetCandidates']) == 1
    assert card['state'] == 'pending' and card['canConfirm']


async def test_intent_request_uses_short_verification_without_changing_user_config(setup, monkeypatch):
    from test_model_services import create as service_create, payload, route
    from paa_server.modules.model_services.bindings import bind_job
    settings, sessions, _, c = setup
    service = payload(url='https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1')
    service['models'][0]['model'] = 'deepseek-v4.1-flash'
    saved = await service_create(c['admin'], service)
    routing = route(saved); routing['assistant']['streaming'] = False
    await c['admin'].put('/api/v1/settings/model-routing', json=routing)
    context, _ = await runtime(setup, '生成今天日报，交之前让我看一眼')
    async with sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        context.model_binding = await bind_job(db, job, settings)
    context.intent_model = None
    calls = []
    async def respond(request):
        body = json.loads(request.content); calls.append(body)
        assert body['max_tokens'] == 2000 and body['enable_thinking'] is False and 'reasoning_effort' not in body
        assert not body.get('tools')
        result = {'allowed': True, 'quote': '生成今天日报，交之前让我看一眼', 'reason': ''}
        return httpx.Response(200, json={'choices': [{'message': {'role': 'assistant', 'content': json.dumps(result)}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 120, 'completion_tokens': 40, 'total_tokens': 160}})
    monkeypatch.setattr('paa_server.integrations.models.transport.client', lambda _: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    assert (await authorize_intent(context, {'action': 'generate_report', 'submitAfter': True}))[0]
    assert len(calls) == 1 and context.calls == 1


async def test_changed_retry_returns_saved_receipt_without_rewriting_or_rechecking(setup):
    _, _, _, c = setup
    context, _ = await runtime(setup, '创建报价方案')
    saved = await execute(context, step=1, action='create_work', changes={'title': '报价方案'})
    retry = await execute(context, step=1, action='create_work', changes={'title': '报价方案', 'summary': '自行添加的内容'})
    assert retry['state'] == 'conflict'
    assert retry['existingOperation'] == saved
    assert len(context.intent_model.inputs) == 1
    item = (await c['employee'].get('/api/v1/work-items/' + saved['objectId'])).json()
    assert item['revision'] == 1 and item['summary'] == ''
