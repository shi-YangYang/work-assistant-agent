"""Offline normalization of all first observations; never sends or retries a model request."""
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT/'artifacts/spec068/repair-performance'


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    global OUT
    spec = importlib.util.spec_from_file_location('repair_comparison', Path(__file__).with_name('repair-perf-run.py'))
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    OUT = harness.OUT
    case_path = OUT/'cases-explicit-report.json'
    cases = read(case_path if case_path.exists() else OUT/'cases.json')
    frozen = {case['alias']: case for case in cases['pairs']}
    observations = []
    for directory in sorted((OUT/'observations').iterdir()):
        if not (directory/'result.json').exists():
            continue
        original = read(directory/'result.json')
        before, after, trace = [read(directory/(name+'.json')) for name in ('before', 'after', 'trace')]
        case = frozen[original['alias']]
        count = harness.counts(trace, after)
        normalized = {**original, 'counts': count}
        checks = harness.invariants(case, normalized, before, after)
        timings = [row for row in trace if row['kind'] == 'repair_timing']
        first_body = [row['time'] for row in timings if row['timing'].get('event') == 'model.first_body']
        admission = read(directory/'admission.json')['sendUnixTime']
        generation = [row for row in trace if row['kind'] == 'tool_dispatch' and row.get('tool') == 'generate_image']
        image_rejections = []
        for row in trace:
            if row['kind'] == 'tool_dispatch_result' and row.get('tool') == 'generate_image':
                try:
                    body = json.loads(row.get('content', ''))
                except (ValueError, TypeError):
                    continue
                if body.get('code') == 'image_input':
                    image_rejections.append({'toolCallId': row.get('toolCallId'), 'message': body.get('message')})
        diagnostic = original['alias'] in ('report-low-1', 'report-low-2')
        settings = original['settings']
        checks['expectedEffort'] = settings['reasoning']['selected']['effort'] == case['effort']
        checks['expectedPermission'] = settings['execution']['executionMode'] == 'auto' and not settings['execution']['fullAccessConfirmed']
        checks['emptyMemory'] = settings['memory']['markdown'] == ''
        checks['freshReportState'] = not before['company_report'] and not before['company_report_revision']
        if case['id'] == 'report':
            reports = after['company_report']
            body = '\n'.join(str(value) for item in reports for value in item['content'].values())
            checks['sourceFactsPresent'] = bool(reports) and '5份' in body and '2份' in body
            checks['sourceRecordMatches'] = bool(reports) and all(set(item['source_ids']) <= {row['id'] for row in after['company_work_revision']} and item['source_ids'] for item in reports)
            checks['periodCorrect'] = bool(reports) and all(item['period'] == '2026-10-12' and item['period_end'] == '2026-10-18' for item in reports)
        observations.append({
            'alias': original['alias'], 'case': case['id'], 'effort': case['effort'],
            'repetition': case['repetition'], 'version': original['version'], 'order': case['order'],
            'diagnosticOnly': diagnostic, 'artifact': str(directory.relative_to(OUT)),
            'metrics': original['metrics'],
            'firstUpstreamBodySeconds': min(first_body)-admission if first_body else None,
            'upstreamBodyDefinition': 'First upstream event can be a tool-call body; not user-visible text',
            'counts': {key: count[key] for key in ('totalProviderRequests', 'modelRequestsByKind', 'mainModelRequests', 'auxiliaryProviderRequests', 'toolRequests', 'toolRequestsByName', 'toolHandlerExecutions', 'controlledImageProviderCalls', 'reportRows', 'businessActions', 'imageRows', 'successfulImages', 'deliverables', 'deliverableRevisions')},
            'currentReportRevision': [row['revision'] for row in after['company_report']],
            'reportSnapshotRows': count['reportRevisions'],
            'imageToolDispatches': len(generation),
            'imagePromptCountCombinations': sum(bool(row.get('arguments', {}).get('prompts')) and ('prompt' in row['arguments'] or 'count' in row['arguments']) for row in generation),
            'imageInputRejections': image_rejections,
            'checks': checks, 'failedChecks': [key for key, value in checks.items() if not value],
            'rawInvariantCorrection': 'Original jobSucceeded only allowed succeeded; normal answer state awaiting_input + completed is valid. Raw result retained.' if 'jobSucceeded' in original['invariants'] else None,
            'taskOutcome': original['message']['job'].get('taskOutcome'),
            'exception': original.get('exception'),
        })
    formal = [item for item in observations if not item['diagnosticOnly']]
    formal_count = cases['comparableObservations']
    diagnostic_count = cases['diagnosticObservations']
    if len(formal) != formal_count or len(observations) != cases['observations']:
        raise RuntimeError('Do not summarize an incomplete campaign')
    summaries = []
    pairs = []
    for case in ('ordinary', 'report', 'images'):
        for effort in ('low', 'high'):
            selected = [row for row in formal if row['case'] == case and row['effort'] == effort]
            if not selected:
                continue
            group = {'case': case, 'effort': effort, 'versions': {}}
            for version in ('baseline', 'candidate'):
                values = [row for row in selected if row['version'] == version]
                durations = [row['metrics']['finalReadbackSeconds'] for row in values]
                group['versions'][version] = {'seconds': durations, 'median': statistics.median(durations), 'min': min(durations), 'max': max(durations),
                    'semanticStateFailures': [row['alias'] for row in values if row['failedChecks']],
                    'mainModelRequests': [row['counts']['mainModelRequests'] for row in values],
                    'auxiliaryProviderRequests': [row['counts']['auxiliaryProviderRequests'] for row in values]}
            b, c = [group['versions'][version]['median'] for version in ('baseline', 'candidate')]
            group.update(deltaSeconds=c-b, deltaPercent=(c/b-1)*100)
            summaries.append(group)
            for repetition in (1, 2):
                matched = {row['version']: row for row in selected if row['repetition'] == repetition}
                b, c = [matched[version] for version in ('baseline', 'candidate')]
                pairs.append({'case': case, 'effort': effort, 'repetition': repetition, 'order': b['order'],
                    'baselineSeconds': b['metrics']['finalReadbackSeconds'], 'candidateSeconds': c['metrics']['finalReadbackSeconds'],
                    'deltaSeconds': c['metrics']['finalReadbackSeconds']-b['metrics']['finalReadbackSeconds'],
                    'mainModelRequests': [b['counts']['mainModelRequests'], c['counts']['mainModelRequests']],
                    'failedChecks': {'baseline': b['failedChecks'], 'candidate': c['failedChecks']}})
    write(OUT/'summary.json', {'baselineSha': '0fd76fed8400d064d2585c4e753d542343eb864f',
        'run': read(OUT/'run.json'), 'formalCount': formal_count, 'diagnosticCount': diagnostic_count,
        'candidateLabel': cases.get('candidateLabel', 'v1'),
        'method': 'Serial AB/BA; each sample own fresh employee/work fixture; both worker concurrency 1; real text model; controlled images 250ms + PNG. Duration ends after persistent report child completion and GET readback.',
        'groups': summaries, 'pairs': pairs, 'observations': observations})
    print(json.dumps({'formal': formal_count, 'diagnostic': diagnostic_count, 'qualityFailureObservations': [row['artifact'] for row in formal if row['failedChecks']],
        'medians': [{key: row[key] for key in ('case', 'effort', 'deltaSeconds', 'deltaPercent')} for row in summaries]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
