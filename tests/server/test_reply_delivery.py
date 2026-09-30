"""Regression cases captured by the employee/admin live evaluation."""
import json
from zoneinfo import ZoneInfo
from app.db.base import now
from types import SimpleNamespace

import pytest
from app.modules.operations.receipts import current_reply
from app.modules.team.sources import citations, current_source_tokens
from app.modules.work.models import ProgressDraft
from app.tasks.models import Job
from test_business_actions import ReplyJudge, create, execute, run_reply, runtime
from test_business_assistant import facts
from app.agent.tools.team import query_team_business

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('available', [True, False])
async def test_worker_delivers_public_results_or_honest_limitation_without_review(setup, monkeypatch, available):
    from fakes import set_delivery
    news = '城市书展今日开幕，地点在城市公园。'
    answer = news + '\n\n来源：[城市新闻](https://example.org/news)' if available else '网页暂时无法读取，未能核实今天的新闻。'
    async def graph(context, *args, **kwargs):
        result = {'url': 'https://example.org/news', 'text': news} if available else {'state': 'unavailable', 'message': '网页无法读取'}
        context.reply_evidence = [{'id': 7, 'tool': 'web_fetch', 'result': json.dumps(result)}]
        await set_delivery(context, answer, task={'goal': '查询城市新闻', 'state': 'completed' if available else 'blocked', 'remaining': [] if available else ['网页读取失败，无法核实当日新闻']})
        return answer
    class Judge:
        async def ainvoke(self, messages):
            raise AssertionError('Ordinary search must not invoke a reviewer')
    monkeypatch.setattr('app.tasks.processing.handlers.invoke_harness', graph)
    result = await run_reply(setup, '联网搜索城市新闻，结果呢？', answer, Judge())
    assert result['reply'] == answer
    assert result['job']['taskOutcome']['state'] == ('completed' if available else 'blocked')
    assert '请补充具体事项' not in result['reply']


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


async def test_required_question_is_preserved_without_repair_or_repeating_saved_action(setup, monkeypatch):
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
        from fakes import set_delivery
        await set_delivery(context, original, business=True, task={'state': 'needs_input', 'remaining': ['选择材料汇总']})
        return original
    async def repair(context, answer, reason, *, model=None):
        calls.append(reason)
        return question
    class Judge:
        async def ainvoke(self, messages):
            payload = json.loads(messages[-1].content)
            return AIMessage(content=json.dumps({'issues': [
                {'kind': 'execution', 'quote': '前项已处理。', 'reason': '执行结果由真实回执说明'},
                {'kind': 'execution', 'quote': '确认后我会修改。', 'reason': '尚未修改'}]}))
    monkeypatch.setattr('app.agent.completion.response_repair.repair_response', repair)
    monkeypatch.setattr('app.tasks.processing.handlers.invoke_harness', graph)
    result = await run_reply(setup, '创建前项，再修改材料汇总下一步', original, Judge(), before=before)
    assert len(calls) == 0 and len(result['actions']) == 1
    assert question in result['reply'] and result['job']['taskOutcome']['state'] == 'partial'
