"""Benchmark evidence must reject wrong ownership and never turn failures into passes."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def module(name):
    path = ROOT / 'scripts/benchmarks/work-checklist' / (name + '.py')
    spec = importlib.util.spec_from_file_location('checklist_benchmark_' + name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_plain_text_fallback_is_not_a_successful_checklist():
    runner = module('run')
    work = {'title': 'synthetic', 'status': 'in_progress', 'dueDate': '2026-10-12', 'body': {'content': [runner.paragraph('first\nsecond')]}}
    result = runner.quality({'id': 'create', 'title': 'synthetic'}, 'candidate', {'items': ['first', 'second']}, [], [work], 'saved')
    assert result['allSourceTextsPresent']
    assert result['checklistCountCorrect'] is False
    assert result['exactTextsInOrder'] is False


@pytest.mark.asyncio
async def test_wrong_owned_suite_is_rejected_before_any_request(tmp_path, monkeypatch):
    runner = module('run')
    monkeypatch.setattr(runner, 'load_environment', lambda _: ({'suite': 'spec059'}, {}))
    with pytest.raises(RuntimeError, match='Exact spec063'):
        await runner.sample(tmp_path, {}, {'id': 'knowledge'}, 'baseline', 'low', 1)
    assert not (tmp_path / 'samples').exists()


@pytest.mark.asyncio
async def test_unfinished_sample_is_not_resent(tmp_path, monkeypatch):
    runner = module('run')
    monkeypatch.setattr(runner, 'load_environment', lambda _: ({'suite': 'spec063'}, {}))
    directory = tmp_path / 'samples/low/knowledge/1/baseline'
    directory.mkdir(parents=True)
    marker = directory / 'admission.json'
    marker.write_text('{"jobId":"already-admitted"}')
    with pytest.raises(RuntimeError, match='unfinished first attempt'):
        await runner.sample(tmp_path, {}, {'id': 'knowledge'}, 'baseline', 'low', 1)
    assert marker.read_text() == '{"jobId":"already-admitted"}'


def test_missing_or_failed_timings_are_preserved_without_claiming_median(tmp_path):
    reporter = module('report')
    for side, times in [('baseline', [5, 6, 7]), ('candidate', [10, None, 11])]:
        for pair, seconds in enumerate(times, 1):
            directory = tmp_path / 'samples/low/create' / str(pair) / side
            directory.mkdir(parents=True)
            row = {'effort': 'low', 'case': 'create', 'side': side, 'pair': pair, 'metrics': {'firstSseTextSeconds': seconds, 'finalReadbackSeconds': seconds}, 'quality': {'checklistCountCorrect': seconds is not None}}
            if seconds is None:
                row['exception'] = {'type': 'TimeoutError'}
            (directory / 'result.json').write_text(json.dumps(row))
    group = reporter.summarize(tmp_path)['pairedGroups'][0]
    assert group['baseline']['metrics']['finalReadbackSeconds']['median'] == 6
    assert group['candidate']['metrics']['finalReadbackSeconds']['median'] is None
    assert group['candidate']['sampleCount'] == 3
    assert group['candidate']['quality'][1]['exception'] == {'type': 'TimeoutError'}
    assert group['candidate']['quality'][1]['checks']['checklistCountCorrect'] is False


def test_complete_final_body_does_not_hide_two_writes_or_parameter_correction():
    runner = module('run')
    result = {'case': 'create', 'quality': {'checklistCountCorrect': True}, 'database': {'actions': [
        {'state': 'succeeded', 'action': 'create_work'}, {'state': 'succeeded', 'action': 'update_work'},
    ], 'workRevisions': [{'revision': 1, 'content': {'body': {'content': [runner.paragraph('仅备注')]}}}]}, 'trace': {'events': [
        {'kind': 'tool_dispatch', 'tool': 'execute_business_action', 'arguments': {'action': 'create_work'}},
        {'kind': 'tool_dispatch', 'tool': 'execute_business_action', 'arguments': {'action': 'update_work'}},
        {'kind': 'tool_dispatch_result', 'tool': 'execute_business_action', 'content': '{"state":"failed","category":"invalid_arguments"}'},
    ]}}
    flow = runner.flow_checks(result, {'items': ['task']})
    assert flow['successfulWrites'] == 2
    assert flow['parameterRejections'] == 1
    assert not flow['initialVersionComplete']
    assert not flow['singleCompleteCreation']
