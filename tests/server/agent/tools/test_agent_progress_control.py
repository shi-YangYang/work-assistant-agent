"""Progress control stops empty loops while preserving recovery and source checks."""
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage

from app.agent.runtime.tool_progress import state
from app.agent.runtime.tool_progress.evidence import result_key, dependencies


def test_single_double_triple_cycles_stop_by_twelfth_new_call_and_replay_is_free():
    for cycle in (1, 2, 3):
        journal = state.create('one-input')
        for index in range(12):
            name = str(index % cycle)
            journal, decision = state.admit(journal, str(index), name, 'same')
            if decision == 'stop':
                break
            journal, _ = state.complete(journal, str(index), name, 'same')
            previous = journal.copy()
            journal, replay = state.admit(journal, str(index), name, 'same')
            assert journal == previous and replay == 'execute'
            if journal['stopped']:
                break
        assert journal['stopped'] and index < 12


def test_valid_pagination_and_changed_source_never_share_result_identity():
    journal = state.create('one-input')
    for index in range(24):
        journal, decision = state.admit(journal, str(index), str(index), 'source')
        journal, _ = state.complete(journal, str(index), str(index), 'source')
        assert decision == 'execute' and not journal['stopped']
    call = {'name': 'read_document', 'args': {'attachment_id': 'a', 'start': 0}}
    assert result_key(call, {'items': [{'text': 'same', 'revision': 1}]}) != result_key(call, {'items': [{'text': 'same', 'revision': 2}]})
    assert result_key(call, {'state': 'failed', 'category': 'invalid_arguments', 'message': 'one'}) == result_key(call, {'state': 'failed', 'category': 'invalid_arguments', 'message': 'another'})


def test_writes_only_reopen_for_relevant_sources_and_pending_replay_is_not_new():
    context = SimpleNamespace(memory_snapshot=None, read_versions={'target': 1}, deliverable_reads={}, document_versions={})
    job = SimpleNamespace(result={})
    call = {'name': 'execute_business_action', 'args': {'target_id': 'target'}}
    first = dependencies(context, job, call)
    context.read_versions['unrelated'] = 2
    assert dependencies(context, job, call) == first
    context.read_versions['target'] = 2
    assert dependencies(context, job, call) != first
    journal, decision = state.admit(state.create('scope'), 'one', 'write', first, prevent_duplicate=True)
    again, replay = state.admit(journal, 'one', 'write', first, prevent_duplicate=True)
    assert again == journal and replay == decision == 'execute'
    journal, decision = state.admit(journal, 'two', 'write', first, prevent_duplicate=True)
    assert decision == 'repeat'
    _, decision = state.admit(journal, 'three', 'write', dependencies(context, job, call), prevent_duplicate=True)
    assert decision == 'execute'


@pytest.mark.asyncio
async def test_catalog_loop_and_worker_recovery_share_bounded_durable_state(setup):
    from _support.agent.business_actions import runtime
    from app.agent.runtime.tool_progress import begin, end
    from app.tasks.models import Job
    context, _ = await runtime(setup)
    call = {'name': 'load_tools', 'args': {'groups': ['work']}, 'id': 'first'}
    assert await begin(context, call) is None
    await end(context, call, ToolMessage(tool_call_id=call['id'], name=call['name'], content=json.dumps({'state': 'loaded', 'groups': ['work']})))
    # A new context/fence resumes the same execution round, not a new loop allowance.
    import dataclasses
    recovered = dataclasses.replace(context, fence=context.fence + 1)
    async with context.sessions.begin() as db:
        job = await db.get(Job, context.job_id)
        job.fence = recovered.fence
    for index in range(6):
        blocked = await begin(recovered, {**call, 'id': f'duplicate-{index}'})
        assert json.loads(blocked.content)['code'] == 'tool_no_progress'
    async with recovered.sessions() as db:
        job = await db.get(Job, context.job_id)
        assert job.result['toolProgress']['stopped']
        assert job.result['taskBudget']['phase'] == 'finalizing'
        assert job.result['taskBudget']['reason'] == 'no_progress'


def test_new_error_wording_and_new_bad_parameters_are_not_successful_progress():
    journal = state.create('one-input')
    for index in range(6):
        journal, decision = state.admit(journal, str(index), f'bad-args-{index}', 'same')
        journal, _ = state.complete(journal, str(index), f'error-{index}', 'same', failed=True)
        assert decision == 'execute'
    assert journal['stopped']


@pytest.mark.asyncio
async def test_complete_page_rejects_empty_offsets_but_explicit_refresh_is_allowed(setup):
    from _support.agent.business_actions import runtime
    from app.agent.runtime.tool_progress import begin, end
    context, _ = await runtime(setup)
    call = {'name': 'read_deliverable', 'args': {'deliverable_id': 'plan', 'offset': 0}, 'id': 'initial'}
    assert await begin(context, call) is None
    await end(context, call, ToolMessage(tool_call_id=call['id'], content=json.dumps({'body': 'all', 'nextOffset': None})))
    extra = {**call, 'args': {**call['args'], 'offset': 20}, 'id': 'empty-page'}
    assert json.loads((await begin(context, extra)).content)['code'] == 'tool_no_progress'
    assert await begin(context, {**call, 'id': 'refresh'}) is None
