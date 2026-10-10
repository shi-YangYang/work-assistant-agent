"""Validate the test observer, not production policy or model word choice."""
import importlib.util
from pathlib import Path


def module(name):
    path = Path(__file__).resolve().parents[2] / 'scripts/company/web-acceptance/agent-audit' / (name + '.py')
    spec = importlib.util.spec_from_file_location('audit_' + name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


loops = module('loops')


def call(name='read_file', *, identifier='1', args=None, job='j1', versions=None, kind='tool_dispatch'):
    return {'kind': kind, 'jobId': job, 'companyId': 'c1', 'ownerId': 'u1', 'toolCallId': identifier, 'tool': name, 'arguments': args or {'path': 'a'}, 'stateVersions': versions or {}}


def test_duplicate_and_self_loop_are_candidates():
    assert loops.candidates([call(), call(identifier='2')])[0]['category'] == 'duplicate'
    assert loops.candidates([call(identifier=str(i)) for i in range(3)])[0]['category'] == 'loop'


def test_two_and_three_tool_cycles():
    for names in (['a', 'b'] * 2, ['a', 'b', 'c'] * 2):
        result = loops.candidates([call(name, identifier=str(i)) for i, name in enumerate(names)])
        assert any(r['category'] == 'cycle' and r['period'] == len(names) // 2 for r in result)


def test_pagination_versions_new_user_turns_and_retry_attempts_not_counted():
    events = [call(args={'cursor': '1'}), call(identifier='2', args={'cursor': '2'}), call(identifier='3', args={'cursor': '1'}, versions={'a': 2}), call(identifier='4', args={'cursor': '1'}, job='j2'), call(identifier='5', args={'cursor': '1'}, kind='tool_attempt_start')]
    assert loops.candidates(events) == []


def test_equivalent_object_key_order_but_not_list_or_code_changes():
    assert loops.fingerprint(call(args={'a': 1, 'b': 2})) == loops.fingerprint(call(args={'b': 2, 'a': 1}))
    assert loops.fingerprint(call(args={'a': [1, 2]})) != loops.fingerprint(call(args={'a': [2, 1]}))
    assert loops.fingerprint(call(args={'code': 'print(10/0)'})) != loops.fingerprint(call(args={'code': 'print(10/2)'}))


def test_secret_redaction_preserves_synthetic_tool_data():
    trace = module('trace')
    value = trace.safe({'arguments': {'text': 'synthetic'}, 'api_key': 'never-save', 'credential': 'never-save'})
    assert value == {'arguments': {'text': 'synthetic'}, 'api_key': '[redacted]', 'credential': '[redacted]'}


def test_approval_requires_current_turn_mutation_kind_and_remaining_allowance():
    approval = module('approval')
    assert not approval.allowed({'action': 'create_work'}, {'workCreate': 0}, {})
    assert not approval.allowed({'action': 'delete_work'}, {'workCreate': 1}, {})
    assert approval.allowed({'action': 'create_work'}, {'workCreate': 1}, {})
    assert not approval.allowed({'action': 'create_work'}, {'workCreate': 1}, {'workCreate': 1})


def test_job_observer_preserves_arguments_result_errors_and_restores_scope(tmp_path):
    import asyncio
    from types import SimpleNamespace
    import pytest
    trace = module('trace')
    trace.OUTPUT = str(tmp_path / 'events.jsonl')
    job = SimpleNamespace(id='job-1', company_id='company', owner_id='owner', attempt=2, fence=3, kind='business')
    calls = []

    async def operation(received, value, *, fail=False):
        calls.append((received, value, fail, dict(trace.scope.get())))
        if fail:
            raise ValueError('fixed synthetic failure')
        return value

    async def exercise():
        marker = object()
        assert await trace.observe_job(operation)(job, marker) is marker
        assert trace.scope.get() == {}
        with pytest.raises(ValueError, match='fixed synthetic failure'):
            await trace.observe_job(operation)(job, marker, fail=True)
        assert trace.scope.get() == {}

    asyncio.run(exercise())
    assert len(calls) == 2
    assert all(c[0] is job and c[3]['jobId'] == 'job-1' for c in calls)


def test_continuation_keeps_memory_settings_and_accepted_receipt(tmp_path, monkeypatch):
    import asyncio
    import hashlib
    import json
    from types import SimpleNamespace
    directory = Path(__file__).resolve().parents[2] / 'scripts/company/web-acceptance/agent-audit'
    monkeypatch.syspath_prepend(str(directory))
    runner = module('run')
    case = {'id': 'synthetic', 'role': 'realEmployee', 'turns': ['first', 'second'], 'mutationBounds': [{}, {}]}
    cases = tmp_path / 'cases.json'
    cases.write_text(json.dumps([case]))
    sha = hashlib.sha256(cases.read_bytes()).hexdigest()
    (tmp_path / 'suite.json').write_text(json.dumps({'caseSha256': sha, 'watchdogSeconds': 1920, 'highRiskRepetition': {'caseIds': []}}))
    previous = tmp_path / 'previous'
    prior = previous / 'synthetic'
    prior.mkdir(parents=True)
    receipt = {'messageId': 'm1', 'jobId': 'j1', 'conversationId': 'c1'}
    accepted = {'turn': 1, 'receipt': receipt}
    (prior / 'accepted.jsonl').write_text(json.dumps(accepted) + '\n')
    (prior / 'settings.json').write_text('{"effort": "max"}')
    frozen = {'caseSha256': sha, 'schema': 'owned', 'runId': 'run', 'applicationCommit': 'commit', 'ids': '', 'repetition': 1, 'timeoutSeconds': 1920, 'concurrency': 1}
    (previous / 'run.json').write_text(json.dumps(frozen))
    monkeypatch.setattr(runner, 'BASE', tmp_path)
    monkeypatch.setattr(runner, 'runner_environment', lambda **kw: (None, {'schema': 'owned', 'runId': 'run', 'commit': 'commit'}, {}))
    seen = []

    async def configure(*args):
        raise AssertionError('Accepted messages must not reset memory/settings')

    async def execute(selected, state, output, materials, timeout, *, previous):
        seen.append((selected['id'], previous))
        assert runner.approval.accepted_turn(runner.http, output / selected['id'], receipt) == 1

    monkeypatch.setattr(runner, 'configure_case', configure)
    monkeypatch.setattr(runner.http, 'execute_case', execute)
    args = SimpleNamespace(metadata='owned', suite=None, materials='materials', output=str(tmp_path / 'continued'), ids='', repetition=1, resume=False, continue_from=str(previous), resume_reason='process interrupted')
    asyncio.run(runner.main(args))
    assert seen == [('synthetic', prior)]
    assert (prior / 'accepted.jsonl').read_text() == json.dumps(accepted) + '\n'


def test_download_validation_requires_parseable_content_and_matching_delivery(tmp_path):
    import hashlib
    from openpyxl import Workbook
    checker = module('downloads')
    path = tmp_path / 'synthetic.xlsx'
    book = Workbook()
    book.active.append(['amount', 150])
    book.save(path)

    def item():
        data = path.read_bytes()
        return {'name': path.name, 'path': str(path), 'size': len(data), 'declaredSize': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

    original = item()
    assert checker.inspect_file(original)['sheets'][0]['sample'] == [('amount', 150)]
    path.write_bytes(b'not actually a workbook')
    assert checker.inspect_file(original)['status'] == 'failed'
    assert checker.inspect_file(item())['status'] == 'failed'


def test_search_progress_distinguishes_changed_queries_from_new_results():
    import json
    events = [{'kind': 'tool_dispatch_result', 'tool': 'web_search', 'toolCallId': str(i), 'content': json.dumps({'query': query, 'items': [{'url': url} for url in urls]})} for i, (query, urls) in enumerate([('first', ['https://one.test']), ('second', ['https://one.test']), ('third', ['https://one.test', 'https://two.test'])])]
    rows = loops.search_progress(events)
    assert [r['newUrlCount'] for r in rows] == [1, 0, 1]
    assert [r['candidateNoNewUrls'] for r in rows] == [False, True, False]
    assert loops.candidates(events) == []


def test_api_confirmation_commits_link_by_action_and_transaction_only(monkeypatch):
    directory = Path(__file__).resolve().parents[2] / 'scripts/company/web-acceptance/agent-audit'
    monkeypatch.syspath_prepend(str(directory))
    reporter = module('report')
    events = [
        {'kind': 'database_commit', 'time': 1, 'transactionId': 'old', 'table': 'company_business_action', 'values': {'id': 'action'}},
        {'kind': 'database_commit', 'time': 3, 'transactionId': 'new', 'table': 'company_business_action', 'values': {'id': 'action'}},
        {'kind': 'database_commit', 'time': 3, 'transactionId': 'new', 'table': 'company_work_revision', 'values': {'id': 'revision'}},
        {'kind': 'database_commit', 'time': 4, 'transactionId': 'other', 'table': 'company_business_action', 'values': {'id': 'unrelated'}},
    ]
    assert reporter.confirmed_commits(events, [{'time': 2}], {'action'}) == events[1:3]


def test_turn_report_excludes_historical_child_job_cards(monkeypatch):
    directory = Path(__file__).resolve().parents[2] / 'scripts/company/web-acceptance/agent-audit'
    monkeypatch.syspath_prepend(str(directory))
    reporter = module('report')
    jobs = {'prior-report': [{'time': 1, 'kind': 'database_commit'}], 'current': [{'time': 2, 'kind': 'worker_job_start'}], 'new-report': [{'time': 3, 'kind': 'database_commit'}]}
    assert reporter.turn_events(jobs, set(jobs), 'current') == jobs['current'] + jobs['new-report']
