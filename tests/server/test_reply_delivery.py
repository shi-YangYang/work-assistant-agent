"""Regression cases captured by the employee/admin live evaluation."""
import json
from zoneinfo import ZoneInfo
from app.db.base import now
from types import SimpleNamespace

import pytest
from app.agent.reply_review import check_segments, reply_segments
from app.modules.operations.receipts import current_reply
from app.modules.team.sources import citations, current_source_tokens
from app.modules.work.models import ProgressDraft
from app.tasks.models import Job
from test_business_actions import ReplyJudge, create, execute, run_reply, runtime
from test_freeform_actions import verdict
from test_business_assistant import facts
from app.agent.tools.team import query_team_business

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('marker', ['[[file:attachment:1:3]]', '[[business:123456789012345678901234]]'])
async def test_trailing_citation_stays_with_retained_or_removed_sentence(marker):
    answer = f'原话：「周五核对范围。」 {marker}\n\n额外内容。'
    parts = reply_segments(answer)
    assert len(parts) == 2 and ''.join(parts) == answer
    assert check_segments(parts, verdict(['information', 'unsupported']), []).text == answer.split('\n\n')[0]
    assert check_segments(parts, verdict(['unsupported', 'information']), []).text == '额外内容。'


async def test_authorized_original_source_is_fact_evidence_but_tool_error_is_not():
    parts = ['员工原话：等待审批。[[business:original]]']
    evidence = [{'id': 7, 'tool': 'read_team_source', 'result': json.dumps({'kind': 'business', 'objectType': 'message', 'content': {'text': '等待审批。'}})}]
    assert check_segments(parts, verdict(['query_fact'], [7]), evidence).text == parts[0]
    for result in ['{"error":"无权查看"}', '读取失败']:
        evidence[0]['result'] = result
        assert check_segments(parts, verdict(['query_fact'], [7]), evidence).text == ''


async def test_current_read_fallback_does_not_inherit_previous_turn_sources(setup):
    _, sessions, users, _ = setup
    await facts(sessions, users['employee'])
    context, _ = await runtime(setup, '查询团队', who='admin')
    result = await query_team_business.coroutine(SimpleNamespace(context=context))
    tokens = current_source_tokens([{'tool': 'query_team_business', 'result': result}])
    assert tokens
    async with sessions() as db:
        job = await db.get(Job, context.job_id)
        _, current = await citations(db, users['admin'], job.access, '查询结果', fallback_tokens=tokens)
        assert {c['token'] for c in current} == set(tokens)
        # Same access, different turn: no current query and no explicit marker.
        _, unrelated = await citations(db, users['admin'], job.access, '创建工作：已完成。')
        assert unrelated == []
        _, explicit = await citations(db, users['admin'], job.access, f'此前来源 [[business:{tokens[0]}]]')
        assert len(explicit) == 1
        _, forged = await citations(db, users['admin'], job.access, '[[business:forged]]', fallback_tokens=['forged'])
        assert forged == []


@pytest.mark.parametrize('submit_after', [False, True])
async def test_report_reply_refreshes_after_generation_and_confirmation(setup, submit_after):
    _, sessions, _, clients = setup
    await create(clients['employee'], title='文档整理', status='done')
    async def enqueue(context):
        await execute(context, step=1, action='generate_report', report_date=now().astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat(), submit_after=submit_after)
    data = await run_reply(setup, '生成日报', '报告正在生成。', ReplyJudge(['execution']), before=enqueue)
    assert '正在处理' in data['reply']
    card = data['actions'][0]
    async with sessions.begin() as db:
        job = await db.get(Job, card['job']['id'])
        job.state = 'succeeded'
        from app.modules.reports.models import Report
        report = await db.get(Report, card['objectId'])
        report.content = {'completed': '文档整理完成', 'ongoing': '', 'blockers': '', 'next': ''}
    updated = (await clients['employee'].get('/api/v1/messages/' + data['id'])).json()
    assert '正在处理' not in updated['reply']
    assert ('等待你的确认' if submit_after else '已完成') in updated['reply']
    if submit_after:
        pending = updated['actions'][0]
        response = await clients['employee'].post(f"/api/v1/business-actions/{pending['id']}/cancel", json={'expectedRevision': pending['revision']})
        assert response.status_code == 200
        latest = (await clients['employee'].get('/api/v1/messages/' + data['id'])).json()
        assert '已取消' in latest['reply'] and '等待你的确认' not in latest['reply']


async def test_saved_suggestion_receipt_and_legacy_message_update_without_rewriting_prose(setup):
    _, sessions, users, clients = setup
    async def propose(context):
        async with sessions.begin() as db:
            job = await db.get(Job, context.job_id)
            db.add(ProgressDraft(company_id=users['employee'].company_id, owner_id=users['employee'].id, message_id=job.target_id,
                                 content={'title': '合同', 'status': 'in_progress', 'summary': '初稿', 'blocker': '', 'nextStep': ''}, tool_key=job.id))
    data = await run_reply(setup, '先给一条建议', '已准备建议。', ReplyJudge(['execution']), before=propose)
    assert '建议：已保存，等待你的确认' in data['reply'] and '未执行' not in data['reply']
    async with sessions.begin() as db:
        draft = await db.get(ProgressDraft, data['drafts'][0]['id'])
        draft.status = 'ignored'
    latest = (await clients['employee'].get('/api/v1/messages/' + data['id'])).json()
    assert '建议：已忽略' in latest['reply']
    row = SimpleNamespace(reply='本次没有保存新的业务操作结果，未执行创建、修改、提交或删除。')
    assert current_reply(row, None, [], [draft]) == '进展建议：已忽略。'
    row.reply = ''
    assert current_reply(row, None, [], [draft]) == ''
    row.reply = '用户原话：报告正在处理。'
    assert current_reply(row, None, [], [draft]) == row.reply


async def test_legacy_report_receipt_is_refreshed_without_editing_free_text():
    cards = [{'action': 'submit_report', 'label': '提交报告', 'state': 'pending'}]
    row = SimpleNamespace(reply='生成报告：正在处理。')
    assert current_reply(row, None, cards, []) == '提交报告：等待你的确认。'
    row.reply = '这是引用：生成报告：正在处理。'
    assert current_reply(row, None, cards, []) == row.reply


@pytest.mark.parametrize('state,expected', [('failed', '未完成'), ('awaiting_retry', '未完成'), ('cancelled', '已取消')])
async def test_report_reply_uses_child_failure_instead_of_stale_running_state(state, expected):
    row = SimpleNamespace(reply='生成报告：正在处理。')
    job = SimpleNamespace(result={'replyReceipt': {'prefix': '', 'suffix': ''}})
    cards = [{'action': 'generate_report', 'label': '生成报告', 'state': 'running', 'job': {'state': state}}]
    assert current_reply(row, job, cards, []) == f'生成报告：{expected}。'
    assert current_reply(row, None, cards, []) == f'生成报告：{expected}。'


async def test_legacy_receipt_with_newly_available_title_still_refreshes():
    row = SimpleNamespace(reply='生成报告：正在处理。')
    cards = [{'action': 'generate_report', 'label': '生成报告', 'state': 'succeeded', 'title': '2026-09-28 日报'}]
    assert current_reply(row, None, cards, []) == '生成报告《2026-09-28 日报》：已完成。'


@pytest.mark.parametrize('saved', [False, True])
async def test_required_clarification_is_an_independent_root_after_execution_prose_is_removed(saved):
    parts = ['前项已处理。\n\n', '请选择材料汇总：\n- 第一批\n- 第二批\n\n', '确认后我会更新。']
    evidence = [{'id': 8, 'tool': 'find_work_items', 'result': json.dumps({'items': [{'title': '材料汇总', 'summary': '第一批'}, {'title': '材料汇总', 'summary': '第二批'}]})}]
    value = {'segments': [
        {'index': 0, 'scope_reason': '执行声明', 'scope': 'answer', 'kind': 'execution'},
        {'index': 1, 'scope_reason': '当前必须选择同名对象', 'scope': 'clarification', 'kind': 'query_fact', 'evidence': [8]},
        {'index': 2, 'scope_reason': '将来执行承诺', 'scope': 'answer', 'kind': 'execution'},
    ], 'taskContext': {'state': 'needs_input', 'remaining': ['选择材料汇总条目']}}
    actions = [{'id': 'saved', 'state': 'succeeded', 'details': {'status': 'done'}}] if saved else []
    checked = check_segments(parts, json.dumps(value), evidence, actions)
    assert checked.text == parts[1].strip() and not checked.needs_response
    # The former necessary->execution classification cannot silently drop the question.
    value['segments'][1].update(scope='necessary', supports=[2])
    dropped = check_segments(parts, json.dumps(value), evidence, actions)
    assert not dropped.text and dropped.needs_response and '最小问题' in dropped.response_reason


@pytest.mark.parametrize('kind,evidence_ids', [('query_fact', [999]), ('unsupported', [])])
async def test_clarification_does_not_preserve_unsupported_candidates(kind, evidence_ids):
    value = {'segments': [{'index': 0, 'scope_reason': '所需对象选择，但候选没有证据', 'scope': 'clarification', 'kind': kind, 'evidence': evidence_ids}],
             'taskContext': {'state': 'needs_input', 'remaining': ['选择对象']}}
    result = check_segments(['要选虚构的第一批还是第二批？'], json.dumps(value), [])
    assert not result.text and result.needs_response


@pytest.mark.parametrize('state', ['completed', 'needs_confirmation'])
async def test_extra_invitation_and_existing_confirmation_do_not_require_new_input(state):
    value = {'segments': [
        {'index': 0, 'scope_reason': '所求分析', 'scope': 'answer', 'kind': 'information'},
        {'index': 1, 'scope_reason': '额外邀请用户执行别的操作', 'scope': 'extra', 'kind': 'information'},
    ], 'taskContext': {'state': state, 'remaining': []}}
    result = check_segments(['这是分析。', '要不要继续创建三项工作？'], json.dumps(value), [])
    assert result.text == '这是分析。' and not result.needs_response
    value['segments'][1]['scope'] = 'clarification'
    assert check_segments(['这是分析。', '请再打字确认。'], json.dumps(value), []).text == '这是分析。'


async def test_filtered_required_question_is_repaired_once_without_repeating_saved_action(setup, monkeypatch):
    from langchain_core.messages import AIMessage
    from app.agent.tools.work import find_work_items
    clients = setup[3]
    await create(clients['employee'], '材料汇总', summary='第一批')
    await create(clients['employee'], '材料汇总', summary='第二批')
    question = '请选择材料汇总：\n- 第一批\n- 第二批'
    original = '前项已处理。\n\n' + question + '\n\n确认后我会修改。'
    calls = []
    async def before(context):
        await execute(context, step=1, action='create_work', changes={'title': '前项'})
    async def graph(context, *args, **kwargs):
        result = await find_work_items.coroutine('材料汇总', SimpleNamespace(context=context))
        context.reply_evidence.append({'id': 8, 'tool': 'find_work_items', 'result': result})
        return original
    async def repair(context, answer, reason, *, model=None):
        calls.append(reason)
        return question
    class Judge:
        async def ainvoke(self, messages):
            payload = json.loads(messages[-1].content)
            evidence_id = next(item['id'] for item in payload['toolEvidence'] if item['tool'] == 'find_work_items')
            if len(payload['segments']) == 1:
                segments = [{'index': 0, 'scope_reason': '必要对象选择', 'scope': 'clarification', 'kind': 'query_fact', 'evidence': [evidence_id]}]
            else:
                segments = [{'index': 0, 'scope_reason': '执行声明', 'scope': 'answer', 'kind': 'execution'},
                    {'index': 1, 'scope_reason': '依附将来执行的旧错误分类', 'scope': 'necessary', 'supports': [2], 'kind': 'query_fact', 'evidence': [evidence_id]},
                    {'index': 2, 'scope_reason': '执行承诺', 'scope': 'answer', 'kind': 'execution'}]
            return AIMessage(content=json.dumps({'segments': segments, 'taskContext': {'state': 'needs_input', 'remaining': ['选择材料汇总']}}))
    monkeypatch.setattr('app.agent.response_repair.repair_response', repair)
    monkeypatch.setattr('app.tasks.handlers.invoke_harness', graph)
    result = await run_reply(setup, '创建前项，再修改材料汇总下一步', original, Judge(), before=before)
    assert len(calls) == 1 and len(result['actions']) == 1
    assert question in result['reply'] and result['job']['taskOutcome']['state'] == 'partial'
