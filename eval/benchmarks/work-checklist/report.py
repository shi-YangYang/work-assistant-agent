"""Summarize raw paired observations without hiding failed samples or inferring P95."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
from statistics import median


def summarize(root):
    groups = defaultdict(list)
    for path in sorted((root / 'samples').glob('*/*/*/*/result.json')):
        row = json.loads(path.read_text())
        groups[(row['effort'], row['case'], row['side'])].append(row)
    result = []
    for effort, case in sorted({(key[0], key[1]) for key in groups}):
        group = {'effort': effort, 'case': case}
        for side in ('baseline', 'candidate'):
            rows = groups[(effort, case, side)]
            metrics = {}
            for key in ('firstSseTextSeconds', 'finalReadbackSeconds'):
                values = [row['metrics'][key] for row in rows if row['metrics'].get(key) is not None]
                metrics[key] = {'values': values, 'median': median(values) if len(values) == 3 else None}
            group[side] = {'sampleCount': len(rows), 'metrics': metrics, 'calls': [{'pair': row['pair'], 'modelAttempts': row.get('trace', {}).get('modelAttempts'), 'providerRequests': row.get('trace', {}).get('providerRequests'), 'tools': row.get('trace', {}).get('tools'), 'inputTokens': sum(item.get('actual_input_tokens') or 0 for item in row.get('database', {}).get('usage', [])), 'outputTokens': sum(item.get('actual_output_tokens') or 0 for item in row.get('database', {}).get('usage', []))} for row in rows], 'quality': [{'pair': row['pair'], 'state': row.get('message', {}).get('job', {}).get('state'), 'checks': {key:value for key,value in row.get('quality', {}).items() if isinstance(value, bool)}, 'exception': row.get('exception')} for row in rows]}
        alarms = []
        for metric in ('firstSseTextSeconds', 'finalReadbackSeconds'):
            baseline = group['baseline']['metrics'][metric]['median']
            candidate = group['candidate']['metrics'][metric]['median']
            if baseline is not None and candidate is not None and candidate > baseline * 1.2 and candidate - baseline > 2:
                alarms.append(metric)
        group['performanceInvestigate'] = alarms
        group['flow'] = {side: [{'pair': row['pair'], 'checks': row.get('flow')} for row in groups[(effort, case, side)]] for side in ('baseline', 'candidate')}
        result.append(group)
    return {'timingDefinition': 'HTTP send to SSE body / terminal readback, not browser paint', 'pairedGroups': result, 'journeys': [json.loads(p.read_text()) for p in sorted((root / 'journeys').glob('*/*/result.json'))]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    target = Path(args.output)
    if target.exists():
        raise RuntimeError('Refusing to overwrite an existing summary')
    target.write_text(json.dumps(summarize(Path(args.evidence)), ensure_ascii=False, indent=2) + '\n')
