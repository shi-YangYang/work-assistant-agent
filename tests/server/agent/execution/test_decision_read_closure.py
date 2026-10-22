"""Original-model read decisions, with receipts and coverage kept separate."""
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.agent.runtime import decision_flow as flow
from app.agent.tools.resources.documents import read_document
from app.tasks.context import RunContext
from _support.agent.fakes import ReviewedFixtureModel
from _support.agent.response_delivery import run


def state():
    return RunContext('owner', 'company', 'job', 1, None, SimpleNamespace()), SimpleNamespace(result={})


def batch(identifier, *calls):
    return AIMessage(id=identifier, content='', tool_calls=list(calls))


def call(identifier, need, *, name='read_document', resolved=None, scope='fact', **metadata):
    return {'id': identifier, 'name': name, 'args': {'_flow': {
        'need': need, 'scope': scope, **({'resolved': resolved} if resolved is not None else {}), **metadata}}}


def returned(context, job, original, result):
    response = batch('model-' + original['id'], original)
    flow.receive(context, job, response)
    cleaned, control = flow.clean(original)
    assert flow.begin(context, job, cleaned, response, control) is None
    key = flow.identity(response, cleaned)
    flow.end(context, job, {**cleaned, 'decisionId': key}, ToolMessage(
        name=cleaned['name'], tool_call_id=cleaned['id'], content=json.dumps(result)))
    return key


def text_result(*, full=False):
    return {'sourceComplete': full, 'readScope': {'allExtractedTextReturned': full}, 'items': [{'text': 'actual excerpt'}]}


@pytest.mark.parametrize('name,result,scope', [
    ('read_document', text_result(full=True), 'full'),
    ('web_search', {'items': [{'url': 'https://example.org', 'snippet': 'official documentation'}]}, 'link'),
    ('web_fetch', {'evidenceType': 'page_text', 'text': 'actual excerpt', 'truncated': False}, 'fact'),
])
def test_read_only_coverage_closes_before_a_redundant_tool(name, result, scope):
    context, job = state()
    key = returned(context, job, call('first', '所需事实', name=name, scope=scope), result)
    assert flow.current(context, job)['requirements']['所需事实'] == {'scope': scope}
    extra = call('extra', '', name=name, resolved={'所需事实': [key]}, scope=scope)
    response = batch('review', extra)
    flow.receive(context, job, response)
    value = flow.current(context, job)
    assert value['phase'] == 'delivering' and value['next'] == 'answer'
    assert value['requirements']['所需事实']['receipts'] == [key]
    cleaned, control = flow.clean(extra)
    assert json.loads(flow.begin(context, job, cleaned, response, control).content)['code'] == 'exploration_closed'
    assert name not in flow.available(value, {name, 'save_deliverable'})
    assert 'save_deliverable' in flow.available(value, {name, 'save_deliverable'})


@pytest.mark.parametrize('reverse', [False, True])
def test_parallel_covered_need_does_not_suppress_unresolved_sibling(reverse):
    context, job = state()
    key = returned(context, job, call('a', '预算'), text_result())
    a = call('repeat-a', '预算', resolved={'预算': [key]})
    b = call('b', '交付时间', resolved={})
    response = batch('parallel', *(reversed([a, b]) if reverse else [a, b]))
    flow.receive(context, job, response)
    value = flow.current(context, job)
    assert value['phase'] == 'exploring'
    assert value['requirements']['预算']['receipts'] == [key]
    assert not value['requirements']['交付时间'].get('receipts')
    for original in response.tool_calls:
        cleaned, control = flow.clean(original)
        stopped = flow.begin(context, job, cleaned, response, control)
        assert (stopped is not None) == (original['id'] == 'repeat-a')
    assert '交付时间' in flow.notice(value)


@pytest.mark.parametrize('name,result', [
    ('find_documents', {'items': [{'id': 'directory'}]}),
    ('read_document', text_result()),
    ('read_document', {'pageRefs': ['prepared-pixels'], 'state': 'ready'}),
    ('web_fetch', {'evidenceType': 'page_text', 'text': 'excerpt', 'truncated': True}),
    ('read_document', {'state': 'failed', 'category': 'permission_denied'}),
])
def test_full_requirement_cannot_be_resolved_by_directory_partial_pixels_or_failure(name, result):
    context, job = state()
    key = returned(context, job, call('source', '全文检查', name=name, scope='full'), result)
    extra = call('continue', '全文检查', resolved={'全文检查': [key]})
    flow.receive(context, job, batch('review', extra))
    value = flow.current(context, job)
    assert value['phase'] == 'exploring'
    assert value['requirements']['全文检查'] == {'scope': 'full'}


def test_source_revision_only_reopens_the_affected_covered_need():
    context, job = state()
    context.document_versions.update(a=1, b=1)
    keys = {}
    for source in ('a', 'b'):
        original = call(source, source)
        original['args']['attachment_id'] = source
        keys[source] = returned(context, job, original, {**text_result(), 'attachment': {'id': source, 'extraction': {'revision': 1}}})
    flow.receive(context, job, batch('review', call('extra', '', resolved={need: [key] for need, key in keys.items()})))
    assert flow.current(context, job)['phase'] == 'delivering'
    job.result = json.loads(json.dumps(job.result))
    context.document_versions['a'] = 2
    value = flow.refresh(context, job)
    assert value['phase'] == 'exploring'
    assert not value['requirements']['a'].get('receipts')
    assert value['requirements']['b']['receipts'] == [keys['b']]


@pytest.mark.parametrize('metadata', [{}, {'resolved': 'bad'}, {'resolved': {'x': []}}, {'resolved': {'x': ['unknown']}}])
def test_legacy_invalid_or_unknown_receipts_never_close_or_force_a_repair(metadata):
    context, job = state()
    returned(context, job, call('source', 'x'), text_result())
    original = {'id': 'legacy', 'name': 'read_document', 'args': {'_flow': metadata}}
    response = batch('review', original)
    flow.receive(context, job, response)
    cleaned, control = flow.clean(original)
    assert flow.current(context, job)['phase'] == 'exploring'
    assert flow.begin(context, job, cleaned, response, control) is None


def test_direct_answer_does_not_forge_coverage_or_require_a_tool_round():
    context, job = state()
    returned(context, job, call('source', '条件与例外'), text_result())
    flow.receive(context, job, AIMessage(id='answer', content='只能确认已提供的部分。'))
    value = flow.current(context, job)
    assert value['phase'] == 'delivering' and value['next'] == 'answer'
    assert value['requirements']['条件与例外'] == {'scope': 'fact'}


def test_review_schema_is_required_only_on_reads_and_does_not_modify_registered_tools():
    from app.agent.tools.resources.deliverables import save_deliverable
    original = read_document.tool_call_schema.model_json_schema()
    read, save = flow.schemas([read_document, save_deliverable], reviewing=True)
    parameters = read['function']['parameters']
    assert parameters['properties']['_flow']['required'] == ['need', 'resolved']
    assert '_flow' in parameters['required']
    assert '_flow' not in save['function']['parameters']['required']
    assert read_document.tool_call_schema.model_json_schema() == original


class ReadCoverageModel(ReviewedFixtureModel):
    calls: int = 0
    redundant: bool = False

    async def _agenerate(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            original = call('budget', '预算', route='fact')
        elif self.calls == 2:
            receipt = next(json.loads(m.content)['_flow']['receipt'] for m in messages if isinstance(m, ToolMessage) and m.tool_call_id == 'budget')
            original = call('delivery', '交付时间', resolved={'预算': [receipt]})
            definition = next(tool for tool in kwargs['tools'] if tool['function']['name'] == 'read_document')
            assert definition['function']['parameters']['properties']['_flow']['required'] == ['need', 'resolved']
        elif self.calls == 3 and self.redundant:
            receipt = next(json.loads(m.content)['_flow']['receipt'] for m in messages if isinstance(m, ToolMessage) and m.tool_call_id == 'delivery')
            original = call('redundant', '', resolved={'交付时间': [receipt]})
        else:
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content='预算 12000 元，交付时间为 11 月 6 日。'))])
        original['args'].update(attachment_id='controlled-source', start=0 if self.calls == 1 else self.calls)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content='', tool_calls=[original]))])


@pytest.mark.asyncio
@pytest.mark.parametrize('redundant', [False, True])
async def test_real_graph_read_decision_runs_before_dispatch_without_extra_model_node(setup, monkeypatch, redundant):
    invoked = []

    async def read(attachment_id, start, runtime, **kwargs):
        invoked.append(start)
        return json.dumps({**text_result(), 'items': [{'text': '预算 12000 元' if start == 0 else '交付时间 11 月 6 日'}]})

    monkeypatch.setattr(read_document, 'coroutine', read)
    model = ReadCoverageModel(model='controlled-read-flow', api_key='no-network', redundant=redundant)
    result, stored = await run(setup, model, '这份材料预算多少、什么时候交付？')
    assert result['reply'] == '预算 12000 元，交付时间为 11 月 6 日。'
    assert invoked == [0, 2]
    assert model.calls == (4 if redundant else 3)
    value = stored['decisionFlow']
    assert value['phase'] == 'delivering'
    assert value['requirements']['预算']['receipts']
    assert bool(value['requirements']['交付时间'].get('receipts')) == redundant
    assert not stored.get('deliveryRepairs')


def test_covered_need_does_not_block_server_required_conflict_refresh():
    context, job = state()
    original = call('source', '工作正文', name='get_work_item')
    original['args']['work_id'] = 'work'
    context.read_versions['work'] = 1
    key = returned(context, job, original, {'id': 'work', 'revision': 1})
    flow.receive(context, job, batch('review', call('extra', '', resolved={'工作正文': [key]})))
    context.refresh_work_versions['work'] = 1
    read = call('refresh', '工作正文', name='get_work_item', resolved={})
    read['args'].update(work_id='work', body_start=0)
    cleaned, control = flow.clean(read)
    assert flow.begin(context, job, cleaned, batch('refresh-batch', read), control) is None


@pytest.mark.parametrize('reverse', [False, True])
def test_full_scope_upgrade_wins_over_sibling_fact_resolution(reverse):
    context, job = state()
    key = returned(context, job, call('source', '检查合同'), text_result())
    resolve = call('resolve', '', resolved={'检查合同': [key]})
    upgrade = call('upgrade', '检查合同', scope='full', resolved={})
    response = batch('upgrade-batch', *(reversed([resolve, upgrade]) if reverse else [resolve, upgrade]))
    flow.receive(context, job, response)
    value = flow.current(context, job)
    assert value['phase'] == 'exploring'
    assert value['requirements']['检查合同'] == {'scope': 'full'}


def test_refresh_without_source_change_does_not_assign_persistent_state():
    context, job = state()
    original = job.result
    flow.refresh(context, job)
    assert job.result is original
    returned(context, job, call('source', '预算'), text_result())
    original = job.result
    flow.refresh(context, job)
    assert job.result is original


def test_covered_need_can_follow_a_real_failed_execution_without_ordinary_reopening():
    context, job = state()
    key = returned(context, job, call('source', '字段结构'), text_result())
    execute = call('execute', '执行统计', name='run_python', resolved={'字段结构': [key]})
    failure = returned(context, job, execute, {'state': 'failed', 'category': 'invalid_arguments',
        'recovery': {'owner': 'assistant', 'nextAction': 'repair'}})
    assert flow.current(context, job)['phase'] == 'executing'
    retry = call('retry', '字段结构', resolved={}, after=failure)
    cleaned, control = flow.clean(retry)
    assert flow.begin(context, job, cleaned, batch('retry-batch', retry), control) is None
    assert flow.current(context, job)['phase'] == 'recovering'


def test_first_read_after_catalog_loading_still_requires_a_fact_need():
    schema = flow.schemas([read_document], tracking=True)[0]['function']['parameters']
    assert schema['properties']['_flow']['required'] == ['route', 'need']
    assert '_flow' in schema['required']
