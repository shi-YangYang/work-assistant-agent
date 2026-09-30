"""Regression of bounded outcomes, field semantics and server-owned display facts."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from app.agent.actions.intent import IntentCheckFailed
from app.agent.actions.operations import execute
from app.agent.completion.reply_review import check_issues, ReviewFormatError
from app.agent.context.request_clock import instruction
from app.modules.team.agent_queries import append_query_summary
from app.tasks.feedback.outcomes import derive
from test_assistant_execution import ReceiptJudge
from test_business_actions import create, read_work, runtime
from test_response_delivery import DeliveryModel, run

pytestmark = pytest.mark.asyncio


class CapabilityModel(DeliveryModel):
    business: bool = True
    review_calls: int = 0

    async def ainvoke(self, input, config=None, *, stop=None, **kwargs):
        if isinstance(input, list) and isinstance(input[-1], HumanMessage):
            try:
                payload = json.loads(input[-1].content)
            except (TypeError, ValueError):
                payload = {}
            if payload.get('task') == 'business_reply_review':
                self.review_calls += 1
                return AIMessage(content=json.dumps({'issues': [{'kind': 'capability', 'reason': '当前角色不能修改他人的工作', 'quote': self.answer}]}))
        return await super().ainvoke(input, config, stop=stop, **kwargs)

    async def _agenerate(self, *args, **kwargs):
        result = await super()._agenerate(*args, **kwargs)
        result.generations[0].message.tool_calls[0]['args']['business_requested'] = self.business
        return result


async def test_capability_refusal_closes_as_blocked_without_retrying_forbidden_work(setup):
    # A bad completed summary must not override the independently classified
    # refusal, force a repair action, or make the user answer an impossible ask.
    fake = CapabilityModel(model='controlled', api_key='unused', answer='我不能修改同事的工作；需要由他本人操作。')
    result, stored = await run(setup, fake, '帮同事随便找个工作，改成完成')
    assert result['reply'] == fake.answer
    assert result['job']['taskOutcome']['state'] == 'blocked'
    assert result['job']['taskOutcome']['nextAction'] == 'none'
    assert fake.calls == fake.review_calls == 1
    assert not stored.get('deliveryRepairs') and not result['actions']
    assert (await setup[3]['employee'].get('/api/v1/work-items')).json()['items'] == []


async def test_capability_keeps_other_completed_actions_but_missing_input_still_asks():
    answer = '本人事项已保存；无权代改同事工作。'
    reviewed = check_issues(answer, json.dumps({'issues': [{'kind': 'capability', 'reason': '不能代改同事', 'quote': '无权代改同事工作。'}]}), [], task={'state': 'completed'})
    job = SimpleNamespace(state='succeeded', error='', result={'taskInterpretation': reviewed.task})
    outcome = derive(job, [{'state': 'succeeded', 'label': '创建工作', 'title': '本人事项'}])
    assert outcome['state'] == 'partial' and outcome['nextAction'] == 'none'
    assert outcome['completed'] == ['创建工作《本人事项》'] and reviewed.text == answer
    ordinary = check_issues('哪个工作？', '{"issues":[]}', [], task={'state': 'needs_input', 'remaining': ['选择工作']})
    job.result = {'taskInterpretation': ordinary.task}
    assert derive(job)['nextAction'] == 'reply'
    missing = check_issues('已经办好了', json.dumps({'issues': [{'kind': 'missing_action', 'reason': '当前已授权新建事项没有执行'}]}), [], task={'state': 'completed'})
    assert missing.needs_action
    with pytest.raises(ReviewFormatError):
        check_issues(answer, json.dumps({'issues': [{'kind': 'capability', 'reason': '不可用', 'quote': '编造拒绝语句'}]}), [])


async def test_progress_cannot_be_written_as_blocker_then_valid_split_saves_once(setup):
    clients = setup[3]
    work = await create(clients['employee'], '新人培训', summary='准备8人培训')
    context, sent = await runtime(setup, '更新新人培训：8人名单已确认，但讲师时间没确定；记为有阻碍，下一步周五联系讲师。')
    requested = [
        {'quote': '8人名单已确认', 'kind': 'progress', 'field': 'blocker'},
        {'quote': '讲师时间没确定', 'kind': 'obstacle', 'field': 'blocker'},
        {'quote': '记为有阻碍', 'kind': 'status', 'field': 'status'},
        {'quote': '下一步周五联系讲师', 'kind': 'next_action', 'field': 'nextStep'},
    ]
    context.intent_model = ReceiptJudge(requested_changes=requested)
    await read_work(context, work['id'])
    args = {'step': 1, 'action': 'update_work', 'target_id': work['id'], 'expected_revision': 1}
    changes = {'status': 'blocked', 'blocker': '8人名单已确认，讲师时间没确定', 'nextStep': '周五联系讲师'}
    with pytest.raises(IntentCheckFailed):
        await execute(context, **args, changes=changes)
    before = (await clients['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert before['revision'] == 1 and before['blocker'] == ''
    requested[0]['field'] = 'summary'
    context.intent_model = ReceiptJudge(requested_changes=requested)
    missing = await execute(context, **args, changes=changes)
    assert missing['category'] == 'invalid_arguments' and 'summary' in missing['message']
    changes.update(summary='准备8人培训；8人名单已确认', blocker='讲师时间没确定')
    saved = await execute(context, **args, changes=changes)
    assert saved['state'] == 'succeeded'
    after = (await clients['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert after['revision'] == 2 and after['summary'] == changes['summary'] and after['blocker'] == changes['blocker']
    assert after['status'] == 'blocked' and after['nextStep'] == '周五联系讲师'
    assert len((await clients['employee'].get('/api/v1/messages/' + sent['messageId'])).json()['actions']) == 1


async def test_explicit_user_field_choice_remains_valid(setup):
    work = await create(setup[3]['employee'], '测试模板')
    context, _ = await runtime(setup, '仅把阻碍字段替换为：已确认名单，待核查讲师。')
    context.intent_model = ReceiptJudge(requested_changes=[{'quote': '阻碍字段替换为：已确认名单，待核查讲师', 'field': 'blocker', 'kind': 'explicit_field'}])
    await read_work(context, work['id'])
    saved = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=1, changes={'blocker': '已确认名单，待核查讲师'})
    assert saved['state'] == 'succeeded' and saved['details']['summary'] == ''
    assert saved['details']['blocker'] == '已确认名单，待核查讲师'


async def test_query_footer_replaces_only_metadata_and_is_idempotent():
    canonical = '\n\n查询依据：\n- 工作 · 全员 · 当前状态：共 1 条，已展示第 1～1 条。查询于 2026-09-29 22:48（Asia/Shanghai）。'
    old = '\n\n查询依据：\n- 工作 · 全员 · 当前状态：共 1 条。查询于 2026-09-29。'
    answer = '跟进计划：先确认讲师。依据是员工确认的阻碍原文。'
    rendered = append_query_summary(answer + old + canonical, canonical)
    assert rendered == answer + canonical
    assert append_query_summary(rendered, canonical) == rendered
    real_explanation = '查询依据：\n员工明确说明讲师时间未确定，这是正文分析。'
    assert append_query_summary(real_explanation, canonical) == real_explanation + canonical
    assert append_query_summary(answer + old, '') == answer + old


async def test_calendar_is_derived_in_company_timezone_across_year_boundary():
    instant = datetime(2026, 12, 31, 18, tzinfo=timezone.utc)
    shanghai = instruction(instant, 'Asia/Shanghai')
    assert '2027-01-01T02:00:00+08:00（周五）' in shanghai
    assert '周一=2026-12-28' in shanghai and '周日=2027-01-03' in shanghai
    utc = instruction(instant, 'UTC')
    assert '2026-12-31T18:00:00+00:00（周四）' in utc


async def test_permission_refusal_preserves_independent_answerable_question():
    answer = '我不能修改同事记录。你本人两项同名工作，想更新哪一项？'
    task = {'state': 'needs_input', 'remaining': ['选择本人要修改的工作', '提供同事记录ID']}
    issue = {'kind': 'capability', 'quote': '我不能修改同事记录。', 'reason': '不能修改其他成员工作', 'resolvable_remaining': ['选择本人要修改的工作']}
    reviewed = check_issues(answer, json.dumps({'issues': [issue]}), [], task=task)
    denied = {'category': 'permission_denied', 'message': '不能代改同事', 'label': '更新工作'}
    outcome = derive(SimpleNamespace(state='awaiting_input', error='', result={'taskInterpretation': reviewed.task, 'toolOutcomes': [denied]}))
    assert outcome['state'] == 'needs_input' and outcome['nextAction'] == 'reply'
    assert outcome['remaining'] == ['选择本人要修改的工作', '不能代改同事']
    assert reviewed.text == answer
    with pytest.raises(ReviewFormatError):
        check_issues(answer, json.dumps({'issues': [{**issue, 'resolvable_remaining': ['编造的新问题']}]}), [], task=task)
