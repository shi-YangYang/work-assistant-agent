"""Pair immutable repair facts and manually reviewed quality, including raw search evidence."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics


def read(path):
    return json.loads(path.read_text())


def search_evidence(root, phase):
    facts = read(root / phase / 'facts.json')
    events = [json.loads(line) for line in (root / phase / 'trace.jsonl').open() if line.strip()]
    output = []
    for case in facts['caseResults']:
        if not case['case'].startswith('R-T09-'):
            continue
        jobs = {job for turn in case['turns'] for job in turn['associatedJobs']}
        seen_urls, seen_fingerprints = set(), set()
        calls = []
        for event in events:
            if event.get('jobId') not in jobs or event['kind'] != 'tool_dispatch_result' or event.get('tool') != 'web_search':
                continue
            result = json.loads(event['content'])
            items = []
            for item in result.get('items', []):
                if not isinstance(item, dict) or not item.get('url'):
                    continue
                source = {key: item.get(key) for key in ('url', 'title', 'snippet')}
                fingerprint = hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                items.append({**source, 'sha256': fingerprint})
            urls = {item['url'] for item in items}
            fingerprints = {item['sha256'] for item in items}
            calls.append({'toolCallId': event.get('toolCallId'), 'query': result.get('query'),
                          'newUrls': len(urls - seen_urls), 'newSourceFingerprints': len(fingerprints - seen_fingerprints),
                          'sources': items, 'category': result.get('category'), 'cacheHit': result.get('cacheHit'),
                          'progressNotice': result.get('progressNotice')})
            seen_urls.update(urls)
            seen_fingerprints.update(fingerprints)
        output.append({'case': case['case'], 'calls': calls, 'uniqueUrls': len(seen_urls),
                       'uniqueSourceFingerprints': len(seen_fingerprints),
                       'zeroNewUrlCalls': sum(call['newUrls'] == 0 for call in calls),
                       'zeroNewSourceCalls': sum(call['newSourceFingerprints'] == 0 for call in calls)})
    return output


def build(root):
    target = root / 'comparison.json'
    if target.exists():
        raise RuntimeError('Refusing to overwrite comparison')
    phases = {}
    quality = {}
    for phase in ('before', 'after'):
        phases[phase] = {case['case']: case for case in read(root / phase / 'facts.json')['caseResults']}
        quality[phase] = {case['case']: case for case in read(root / phase / 'semantic-review.json')['cases']}
    if set(phases['before']) != set(phases['after']):
        raise RuntimeError('Unpaired case set')
    cases = []
    for identifier, before in phases['before'].items():
        after = phases['after'][identifier]
        if [turn['turn'] for turn in before['turns']] != [turn['turn'] for turn in after['turns']]:
            raise RuntimeError('Unpaired turns: ' + identifier)
        turns = []
        for old, new in zip(before['turns'], after['turns'], strict=True):
            old_review = next(t for t in quality['before'][identifier]['turns'] if t['turn'] == old['turn'])
            new_review = next(t for t in quality['after'][identifier]['turns'] if t['turn'] == new['turn'])
            turns.append({'turn': old['turn'], 'beforeSeconds': old['seconds'], 'afterSeconds': new['seconds'],
                          'deltaSeconds': round(new['seconds'] - old['seconds'], 2),
                          'beforeQuality': old_review, 'afterQuality': new_review,
                          'beforeProviderRequests': old['actualProviderHttpRequests'],
                          'afterProviderRequests': new['actualProviderHttpRequests'],
                          'beforeToolAttempts': old['actualToolAttempts'], 'afterToolAttempts': new['actualToolAttempts'],
                          'beforeInputTokens': old['modelTokens']['input_tokens'],
                          'afterInputTokens': new['modelTokens']['input_tokens']})
        cases.append({'case': identifier, 'turns': turns, 'beforeQuality': quality['before'][identifier]['result'],
                      'afterQuality': quality['after'][identifier]['result'],
                      'beforeSeconds': round(sum(t['beforeSeconds'] for t in turns), 2),
                      'afterSeconds': round(sum(t['afterSeconds'] for t in turns), 2)})
    totals = {}
    for phase in ('before', 'after'):
        turns = [t for case in phases[phase].values() for t in case['turns']]
        controls = [t for case in phases[phase].values() if case['case'].startswith('P-chat-') for t in case['turns']]
        totals[phase] = {'cases': len(phases[phase]), 'turns': len(turns), 'seconds': round(sum(t['seconds'] for t in turns), 2),
                         'providerRequests': sum(t['actualProviderHttpRequests'] for t in turns),
                         'toolAttempts': sum(t['actualToolAttempts'] for t in turns),
                         'inputTokens': sum(t['modelTokens']['input_tokens'] for t in turns),
                         'qualityCases': dict(Counter(c['result'] for c in quality[phase].values())),
                         'qualityTurns': dict(Counter(t['result'] for c in quality[phase].values() for t in c['turns'])),
                         'controlMeanSeconds': round(statistics.mean(t['seconds'] for t in controls), 2),
                         'controlMedianSeconds': round(statistics.median(t['seconds'] for t in controls), 2)}
    report = {'role': 'implementation evaluation; independent acceptance is separate', 'totals': totals, 'cases': cases,
              'searchEvidence': {phase: search_evidence(root, phase) for phase in ('before', 'after')},
              'limits': ['Small serial before/after sample, not randomized latency proof.',
                         'Search provider and network can vary; raw source fingerprints retain title and snippet, not just URLs.',
                         'Quality manually checks returned answers, requested scope, persisted fields and actual downloaded files.']}
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'path': str(target), 'totals': totals}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    build(parser.parse_args().root.resolve())
