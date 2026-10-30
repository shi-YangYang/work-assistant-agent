"""Index real repair-comparison evidence; quality verdicts require human review."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

AUDIT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AUDIT))
from report import summarize, read_rows


def build(phase):
    output = phase / 'facts.json'
    if output.exists():
        raise RuntimeError('Refusing to overwrite recorded facts')
    facts = summarize(phase / 'results', phase / 'trace.jsonl', phase / 'worker.log')
    events = read_rows(phase / 'trace.jsonl')
    for case in facts['caseResults']:
        result = json.loads(Path(case['evidence']).read_text())
        by_turn = {row['turn']: row for row in result['turns']}
        for turn in case['turns']:
            row = by_turn[turn['turn']]
            associated = set(turn['associatedJobs'])
            starts = [event for event in events if event.get('jobId') in associated and event['kind'] == 'worker_job_start']
            beginning = min((event['time'] for event in starts), default=0)
            upstream = [event for event in events if event.get('jobId') in associated
                        and event.get('time', 0) >= beginning and event['kind'] == 'upstream_http_start']
            requests = [event for event in upstream if isinstance(event.get('input'), dict)
                        and event['input'].get('model')]
            usage = [event.get('usage') or {} for event in events if event.get('jobId') in associated
                     and event.get('time', 0) >= beginning and event['kind'] == 'model_attempt_result']
            turn['actualProviderHttpRequests'] = len(requests)
            turn['allExternalHttpRequests'] = len(upstream)
            turn['reasoningEfforts'] = dict(Counter(event.get('input', {}).get('reasoningEffort') for event in requests))
            turn['imagePartsSubmitted'] = sum(part.get('type') == 'image_url'
                                              for event in requests for message in event.get('input', {}).get('messages', [])
                                              for part in message.get('parts', []))
            turn['modelTokens'] = {name: sum(item.get(name, 0) or 0 for item in usage)
                                   for name in ('input_tokens', 'output_tokens', 'total_tokens')}
            turn['reply'] = row.get('message', {}).get('reply', '')
            turn['publishedReports'] = row.get('readback', {}).get('weekly')
            turn['downloadedFiles'] = row.get('files', [])
            metric_path = Path(case['evidence']).parent / f'metrics-{turn["turn"]}.json'
            turn['sse'] = json.loads(metric_path.read_text()) if metric_path.exists() else None
            turn['authoritativeResult'] = row.get('message', {}).get('job', {})
    facts['interpretation'] = 'Counts and terminal states are evidence only, not quality PASS; exact source replies/requests/files retained.'
    output.write_text(json.dumps(facts, ensure_ascii=False, indent=2, default=str) + '\n')
    print(json.dumps({'path': str(output), 'cases': facts['casesObserved'], 'turns': facts['turnsObserved'],
                      'seconds': round(sum(t['seconds'] for c in facts['caseResults'] for t in c['turns']), 2)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', type=Path, required=True)
    build(parser.parse_args().phase.resolve())
