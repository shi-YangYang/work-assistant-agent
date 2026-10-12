"""Offline evidence-review replays plus direct-delivery regressions."""
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from app.agent.completion.delivery import assess
from app.agent.completion.review.reply_review import review_reply
from app.agent.completion.evidence.evidence_consistency import observed_evidence, tool_evidence
from app.agent.completion.recovery.response_repair import repair_response
from app.core.digests import digest
from app.tasks.models import Job
from _support.agent.fakes import set_delivery
from _support.agent.business_actions import runtime
from _support.agent.response_delivery import PageDeliveryModel, run


def page(context, **overrides):
    return {'id': 0, 'jobId': context.job_id, 'status': 'success', 'tool': 'web_fetch',
            'result': json.dumps({'evidenceType': 'page_text', 'text': 'Published May 8. The event took place May 7.'}), **overrides}


def test_observed_evidence_pairs_real_calls_and_ignores_model_supplied_arguments():
    actual = {'code': 'print("branch A returned 7")'}
    messages = [AIMessage(content='', tool_calls=[{'id': 'a', 'name': 'run_python', 'args': actual}]),
        ToolMessage(name='run_python', tool_call_id='a', content=json.dumps({
            'state': 'succeeded', 'stdout': 'branch A returned 7', 'arguments': {'code': 'invented'}})),
        ToolMessage(name='web_fetch', tool_call_id='a', content='{}')]
    rows = tool_evidence(messages, 'current')
    assert rows[0]['arguments'] == actual and 'arguments' not in rows[1]
    assert len(tool_evidence(messages[:1], 'current')) == 0
    context = SimpleNamespace(job_id='current', reply_evidence=[{**row, 'id': i} for i, row in enumerate(rows)])
    observed = observed_evidence(context)
    assert len(observed) == 1 and observed[0]['arguments'] == actual
    assert observed[0]['result']['stdout'] == 'branch A returned 7'


@pytest.mark.parametrize('overrides', [
    {'jobId': 'previous'}, {'jobId': None}, {'status': 'error'},
    {'result': '{"evidenceType":"page_text","text":""}'},
    {'result': '{"evidenceType":"page_search","state":"not_found"}'},
    {'tool': 'web_search', 'result': '{"text":"Only a search summary"}'},
    {'tool': 'run_python', 'result': '{"state":"failed","stdout":"partial"}'},
    {'tool': 'run_python', 'result': '{"state":"succeeded","stdout":""}'},
    {'tool': 'find_documents', 'result': '{"items":[{"name":"document.txt"}]}'},
    {'result': 'not JSON'},
])
def test_unread_failed_empty_and_historical_results_do_not_trigger_review(overrides):
    context = SimpleNamespace(job_id='current')
    context.reply_evidence = [page(context, **overrides)]
    assert observed_evidence(context) == []


def test_document_and_table_results_preserve_partial_coverage():
    context = SimpleNamespace(job_id='current')
    document = {'items': [{'citation': '[[file:real:1:0]]', 'text': 'Only this section.', 'ordinal': 0}], 'nextCursor': 1}
    table = {'state': 'succeeded', 'data': {'sample': [[1]], 'truncated': True, 'rows': 200}}
    context.reply_evidence = [page(context, tool='read_document', result=json.dumps(document)),
        page(context, id=1, tool='inspect_table', result=json.dumps(table))]
    assert [row['result'] for row in observed_evidence(context)] == [document, table]


@pytest.mark.asyncio
@pytest.mark.parametrize('issue', [
    {'kind': 'fact', 'quote': '候选正文', 'reason': '缺少来源', 'evidence': []},
    {'kind': 'fact', 'quote': '候选正文', 'reason': '历史来源不同', 'evidence': [1]},
    {'kind': 'missing_response', 'reason': '请用户补充全部资料'},
    {'kind': 'missing_action', 'reason': '请保存工作'},
])
async def test_unsupported_or_out_of_scope_issues_cannot_change_answer_or_authority(setup, issue):
    context, _ = await runtime(setup, '概括已读资料')
    await set_delivery(context, '候选正文')
    context.reply_evidence = [page(context), page(context, id=1, jobId='previous')]
    class Judge:
        async def ainvoke(self, messages):
            payload = json.loads(messages[-1].content)
            assert payload['reviewScope'] == 'evidence_only'
            assert payload['conversationForReferenceOnly'] == []
            assert [row['id'] for row in payload['toolEvidence']] == [0]
            assert not {'currentActions', 'roleCapabilities', 'conversationTask'} & payload.keys()
            return AIMessage(content=json.dumps({'issues': [issue]}, ensure_ascii=False))
    reviewed = await review_reply(context, '候选正文', model=Judge(), business=False, observed=observed_evidence(context))
    assert reviewed.verified and reviewed.text == '候选正文'
    assert not reviewed.needs_action and not reviewed.needs_response
    async with context.sessions() as db:
        record = (await db.get(Job, context.job_id)).result['replyReview']
        assert record['evidenceConsistency']['state'] == 'unavailable' and 'verdict' not in record


@pytest.mark.asyncio
async def test_review_contract_change_invalidates_old_verdict_but_keeps_current_cache(setup, monkeypatch):
    from app.agent.completion.review import reply_review
    version = reply_review.REVIEW_VERSION
    context, _ = await runtime(setup, '概括已读资料')
    answer = 'Published May 8.'
    await set_delivery(context, answer)
    context.reply_evidence = [page(context)]
    calls = []
    class Judge:
        async def ainvoke(self, messages):
            payload = json.loads(messages[-1].content)
            calls.append(payload['version'])
            # Exercise persisted verdict invalidation, not model judgment quality.
            issues = [] if payload['version'] == version else [
                {'kind': 'fact', 'quote': answer, 'reason': 'Stored verdict under the previous contract.', 'evidence': [0]}]
            return AIMessage(content=json.dumps({'issues': issues}))
    judge = Judge()
    with monkeypatch.context() as previous:
        previous.setattr(reply_review, 'REVIEW_VERSION', version - 1)
        old = await review_reply(context, answer, model=judge, business=False, observed=observed_evidence(context))
    current = await review_reply(context, answer, model=judge, business=False, observed=observed_evidence(context))
    cached = await review_reply(context, answer, model=judge, business=False, observed=observed_evidence(context))
    assert old.needs_response
    assert current.verified and not current.needs_response and current.text == answer
    assert cached == current and calls == [version - 1, version]


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['ordinary', 'explicit', 'business', 'numeric', 'old_verdict', 'capacity'])
async def test_completion_does_not_call_judge_for_any_answer_scope(setup, mode):
    context, _ = await runtime(setup, '请核验资料')
    answer = '甲 3 个，乙 4 个，合计 7 个。' if mode == 'numeric' else '依据本段材料可作如下概括。'
    await set_delivery(context, answer)
    context.reply_evidence = [page(context)]
    if mode == 'explicit':
        context.delivery.update(verification_requested=True, verification_quote='请核验资料')
    elif mode == 'business':
        context.delivery['business_requested'] = True
    elif mode == 'old_verdict':
        async with context.sessions.begin() as db:
            job = await db.get(Job, context.job_id)
            job.result = {**job.result, 'replyReview': {'verdict': 'obsolete'}, 'quantitativeReviewInput': 'old'}
    elif mode == 'capacity':
        context.model_binding = {'assistant': {'contextCapability': {'inputLimit': 1}}}
    class ForbiddenJudge:
        async def ainvoke(self, messages):
            pytest.fail('Completion must not request another model')
    reviewed = await assess(context, answer, model=ForbiddenJudge())
    assert reviewed.verified and reviewed.needs_action is (mode == 'business')
    assert reviewed.text == ('' if mode == 'business' else answer)
    assert not reviewed.needs_response


@pytest.mark.asyncio
@pytest.mark.parametrize('changed', ['', 'answer', 'evidence'])
async def test_structured_correction_issues_are_bound_to_the_current_answer(setup, changed):
    context, _ = await runtime(setup, '概括资料')
    answer = 'The source was published May 7.'
    context.reply_evidence = [page(context)]
    issue = {'kind': 'fact', 'quote': answer, 'reason': 'Publication field is May 8, not the event date.', 'evidence': [0]}
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        job.result = {**job.result, 'replyReview': {'answerDigest': digest('old candidate' if changed == 'answer' else answer),
            'evidenceDigest': digest([] if changed == 'evidence' else context.reply_evidence), 'verdict': json.dumps({'issues': [issue]})}}
    class Repair:
        async def ainvoke(self, messages):
            payload = json.loads(messages[-1].content)
            assert 'correctionIssues' not in payload  # old judge verdicts cannot enter live repairs
            return AIMessage(content='The source was published May 8.')
    assert await repair_response(context, answer, issue['reason'], model=Repair()) == 'The source was published May 8.'


@pytest.mark.asyncio
async def test_actual_page_result_delivers_without_review_or_tool_replay(setup, monkeypatch):
    fetches = []
    async def fetch(url, **kwargs):
        fetches.append(url)
        return {'url': url, 'title': 'Source', 'evidenceType': 'page_text',
                'text': 'Published May 8. The event took place May 7.', 'offset': 0, 'truncated': False}
    monkeypatch.setattr('app.integrations.web_research.web_fetch', fetch)
    fake = PageDeliveryModel(model='controlled', api_key='unused',
        answer='The source was published May 8. The event was May 7.')
    result, stored = await run(setup, fake, '阅读网页并分别概括发布时间与活动时间')
    assert len(fetches) == 1 and fake.calls == 2 and fake.reviews == 0
    assert result['reply'] == fake.answer and result['job']['taskOutcome']['state'] == 'completed'
    assert not stored.get('deliveryRepairs') and not stored.get('replyReview')
    assert not any(node['kind'] == 'review' for node in result['job']['nodes'])
    assert stored['webSources']['https://example.org/reference']['fetchState'] == 'read'


@pytest.mark.asyncio
async def test_explicit_offline_evidence_review_keeps_the_frozen_low_effort(setup, monkeypatch):
    context, _ = await runtime(setup, '解释已读内容')
    await set_delivery(context, '这是有依据的概括。')
    context.reply_evidence = [page(context)]
    config = {'baseUrl': 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'model': 'deepseek-v4.1-flash',
        'streaming': False, 'parameters': {'enable_thinking': True, 'reasoning_effort': 'low'}}
    async def resolve(*args):
        return config, 'unused'
    monkeypatch.setattr('app.modules.model_services.bindings.resolve_bound', resolve)
    async def chat(settings, received, key, messages, *, on_event, **kwargs):
        assert received['parameters'] == config['parameters']
        assert json.loads(messages[-1]['content'])['reviewScope'] == 'evidence_only'
        await on_event('started')
        return {'choices': [{'message': {'role': 'assistant', 'content': '{"issues":[]}'}, 'finish_reason': 'stop'}]}
    monkeypatch.setattr('app.integrations.models.chat.chat', chat)
    reviewed = await review_reply(context, context.delivery['answer'], business=False, observed=observed_evidence(context))
    assert reviewed.verified and reviewed.text == context.delivery['answer']
