"""Offline candidates only: never suppress calls or classify them as proven defects."""
from collections import defaultdict
import hashlib
import json


def fingerprint(event):
    # Preserve order for lists, exact code and pagination cursors. Job identifies
    # the user turn; versions separate legitimate reads after successful writes.
    value = [event.get('companyId'), event.get('ownerId'), event.get('jobId'), event.get('tool'), event.get('arguments', {}), event.get('stateVersions', {})]
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def candidates(events):
    calls = [row for row in events if row.get('kind') == 'tool_dispatch']
    groups = defaultdict(list)
    for index, row in enumerate(calls):
        groups[fingerprint(row)].append((index, row))
    found = []
    for key, group in groups.items():
        if len(group) >= 2:
            row = group[0][1]
            found.append({'category': 'loop' if len(group) >= 3 else 'duplicate', 'jobId': row['jobId'], 'tool': row['tool'], 'fingerprint': key, 'count': len(group), 'callIds': [r['toolCallId'] for _, r in group], 'review': 'check new evidence, failures, pagination and user authorization'})
    by_job = defaultdict(list)
    for row in calls:
        by_job[row['jobId']].append(row)
    for job, rows in by_job.items():
        signatures = [fingerprint(r) for r in rows]
        for length in (2, 3):
            for start in range(len(rows) - length * 2 + 1):
                block = signatures[start:start + length]
                if len(set(block)) > 1 and block == signatures[start + length:start + 2 * length]:
                    found.append({'category': 'cycle', 'jobId': job, 'period': length, 'callIds': [r['toolCallId'] for r in rows[start:start + 2 * length]], 'review': 'candidate, not automatic failure'})
    return found


def search_progress(events):
    """Expose changed queries with no new URLs for human review, not failure."""
    seen, rows = set(), []
    for event in events:
        if event.get('kind') != 'tool_dispatch_result' or event.get('tool') != 'web_search':
            continue
        try:
            result = json.loads(event.get('content', ''))
        except (ValueError, TypeError):
            continue
        if not isinstance(result, dict) or not isinstance(result.get('items'), list):
            continue
        urls = {item['url'] for item in result['items'] if isinstance(item, dict) and isinstance(item.get('url'), str)}
        fresh = urls - seen
        rows.append({'callId': event.get('toolCallId'), 'query': result.get('query'), 'resultCount': len(result['items']), 'newUrlCount': len(fresh), 'urls': sorted(urls), 'candidateNoNewUrls': bool(rows) and not fresh})
        seen.update(urls)
    return rows
