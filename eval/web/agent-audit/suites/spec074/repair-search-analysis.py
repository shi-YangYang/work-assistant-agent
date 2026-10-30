"""Offline search chronology and raw-source evidence for real comparison runs."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit


def product_vendor(url):
    parsed = urlsplit(url)
    if parsed.hostname == 'learn.chatgpt.com' and parsed.path.rstrip('/') in ('/docs', '/docs/use-chatgpt'):
        return 'OpenAI'
    if parsed.hostname in ('www.anthropic.com', 'anthropic.com') and parsed.path.startswith('/claude/'):
        return 'Anthropic'
    if parsed.hostname == 'claude.com' and parsed.path.startswith('/product/'):
        return 'Anthropic'
    return None


def union_seconds(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    return round(sum(end - start for start, end in merged), 2)


def analyze(phase):
    output = phase / 'search-analysis.json'
    if output.exists():
        raise RuntimeError('Refusing to overwrite recorded search analysis')
    events = [json.loads(line) for line in (phase / 'trace.jsonl').open() if line.strip()]
    facts = json.loads((phase / 'facts.json').read_text())
    jobs = {job['id']: job for job in json.loads((phase / 'readback.json').read_text())['Job']}
    cases = []
    for case in facts['caseResults']:
        turn = case['turns'][0]
        selected = [event for event in events if event.get('jobId') in turn['associatedJobs']]
        origin = min(event['time'] for event in selected if event['kind'] == 'worker_job_start')
        dispatch = {event['toolCallId']: event for event in selected if event['kind'] == 'tool_dispatch'}
        source_seen, urls_seen, official = set(), set(), {}
        calls, checkpoint = [], None
        searches = 0
        for event in selected:
            if event['kind'] != 'tool_dispatch_result' or event['tool'] not in ('web_search', 'web_fetch'):
                continue
            result = json.loads(event['content'])
            start = dispatch[event['toolCallId']]
            tool = event['tool']
            if tool == 'web_search':
                searches += 1
            sources = []
            for item in result.get('items', []):
                if not isinstance(item, dict) or not item.get('url'):
                    continue
                source = {key: item.get(key) for key in ('url', 'title', 'snippet')}
                sources.append({**source, 'sha256': hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True).encode()).hexdigest()})
            urls = {source['url'] for source in sources}
            fingerprints = {source['sha256'] for source in sources}
            for url in sorted(urls):
                vendor = product_vendor(url)
                if vendor and vendor not in official:
                    official[vendor] = {'url': url, 'toolCallId': event['toolCallId'], 'seconds': round(event['time'] - origin, 2), 'searchNumber': searches, 'evidenceType': 'search_snippet'}
            if tool == 'web_fetch' and result.get('url') == 'https://claude.com/product/overview' and result.get('state') != 'unavailable':
                official.setdefault('Anthropic', {'url': result['url'], 'toolCallId': event['toolCallId'], 'seconds': round(event['time'] - origin, 2), 'searchNumber': searches, 'evidenceType': 'page_body'})
            attempt_starts = [entry for entry in selected if entry.get('toolCallId') == event['toolCallId'] and entry['kind'] == 'tool_attempt_start']
            calls.append({'toolCallId': event['toolCallId'], 'tool': tool, 'arguments': start['arguments'],
                          'startSeconds': round(start['time'] - origin, 3), 'endSeconds': round(event['time'] - origin, 3),
                          'seconds': round(event['time'] - start['time'], 3), 'attempts': len(attempt_starts),
                          'state': result.get('state'), 'code': result.get('code'), 'errorCode': result.get('errorCode'),
                          'query': result.get('query'), 'url': result.get('url'), 'requestedUrl': result.get('requestedUrl'),
                          'sourceDiscovered': result.get('sourceDiscovered'), 'evidenceLevel': result.get('evidenceLevel'),
                          'cacheHit': result.get('cacheHit'), 'newUrls': len(urls - urls_seen),
                          'newSourceFingerprints': len(fingerprints - source_seen), 'sources': sources,
                          'progressNotice': result.get('progressNotice')})
            source_seen.update(fingerprints)
            urls_seen.update(urls)
            if checkpoint is None and len(official) == 2:
                checkpoint = {'seconds': round(event['time'] - origin, 3), 'searchNumber': searches,
                              'toolCallId': event['toolCallId'], 'sources': dict(official),
                              'meaning': 'Both official product links were returned by tools; user asked for links only, not full body verification.'}
        models = [event for event in selected if event['kind'] == 'upstream_http_start' and (event.get('input') or {}).get('model')]
        after = [call for call in calls if checkpoint and call['startSeconds'] > checkpoint['seconds']]
        selected_jobs = [jobs[job] for job in turn['associatedJobs'] if job in jobs]
        stop = [{'jobId': job['id'], 'state': job['state'], 'taskOutcome': job['result'].get('taskOutcome'),
                 'toolProgress': {key: job['result'].get('toolProgress', {}).get(key) for key in ('stalled', 'stopped', 'version')},
                 'taskBudget': {key: job['result'].get('taskBudget', {}).get(key) for key in ('phase', 'reason', 'tools', 'models', 'policy')}} for job in selected_jobs]
        timings = {}
        for tool in ('web_search', 'web_fetch'):
            items = [call for call in calls if call['tool'] == tool]
            timings[tool] = {'dispatches': len(items), 'executionAttempts': sum(call['attempts'] for call in items),
                             'sumSeconds': round(sum(call['seconds'] for call in items), 2),
                             'unionWallSeconds': union_seconds((call['startSeconds'], call['endSeconds']) for call in items),
                             'zeroNewSourceResults': sum(not call['newSourceFingerprints'] for call in items) if tool == 'web_search' else None,
                             'errorCodes': dict(Counter(call['errorCode'] for call in items if call['errorCode']))}
        cases.append({'case': case['case'], 'seconds': turn['seconds'], 'providerRequests': len(models),
                      'tokens': turn['modelTokens'], 'timings': timings, 'firstTwoOfficialLinks': checkpoint,
                      'afterSufficientLinks': {'remainingWallSeconds': round(turn['seconds'] - checkpoint['seconds'], 2) if checkpoint else None,
                                               'newDispatches': dict(Counter(call['tool'] for call in after)),
                                               'newModelRequests': sum(event['time'] - origin > checkpoint['seconds'] for event in models) if checkpoint else None,
                                               'zeroNewSourceSearches': sum(call['tool'] == 'web_search' and not call['newSourceFingerprints'] for call in after)},
                      'stop': stop, 'calls': calls, 'reply': turn['reply']})
    report = {'role': 'implementation evaluation', 'cases': cases,
              'measurement': 'Dispatch duration includes normal tool retries/backoff; calls may overlap, so sumSeconds is not additive elapsed time. Source fingerprints retain url/title/snippet. Earliest sufficient links is an offline observation, not altered model input.'}
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'path': str(output), 'cases': [{key: value for key, value in case.items() if key not in ('calls', 'reply')} for case in cases]}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', required=True, type=Path)
    analyze(parser.parse_args().phase.resolve())
