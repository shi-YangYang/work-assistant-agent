"""Summarize facts and candidate loops; semantic acceptance is a separate review."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re

from loops import candidates, search_progress
from downloads import inspect_file


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def confirmed_commits(events, rows, action_ids):
    # Manual confirmation writes inside the API request, outside worker scope.
    # Its BusinessAction ID and SQL transaction link all committed changes.
    started = min((row['time'] for row in rows), default=float('inf'))
    transactions = {row.get('transactionId') for row in events if row.get('kind') == 'database_commit' and not row.get('jobId') and row.get('time', 0) >= started and row.get('table') == 'company_business_action' and row.get('values', {}).get('id') in action_ids}
    transactions.discard(None)
    return [row for row in events if row.get('kind') == 'database_commit' and not row.get('jobId') and row.get('transactionId') in transactions]


def turn_events(jobs, related, identifier):
    # Follow-up answers may include cards from previous turns. Their child jobs
    # remain evidence, but must not inflate this turn's calls and writes.
    started = min((row['time'] for row in jobs.get(identifier, [])), default=float('inf'))
    return sorted([row for job in related for row in jobs.get(job, []) if row['time'] >= started], key=lambda row: row['time'])


def summarize(root, trace, log):
    events = read_rows(trace)
    jobs = defaultdict(list)
    for event in events:
        job = event.get('jobId') or event.get('scope', {}).get('jobId')
        if job:
            jobs[job].append(event)
    timing = defaultdict(dict)
    for line in log.read_text().splitlines() if log.exists() else []:
        if 'latency {' not in line:
            continue
        try:
            row = json.loads(line.split('latency ', 1)[1])
        except ValueError:
            continue
        key = {'model.first_body': 'firstProviderBodyMs', 'publish.end': 'firstPublishMs', 'task.end': 'taskEndMs'}.get(row['event'])
        if key:
            timing[row['job']].setdefault(key, row['at_ms'])
    results = []
    for path in sorted(root.glob('*/result.json')):
        value = json.loads(path.read_text())
        turns = []
        for turn in value['turns']:
            identifier = (turn.get('receipt') or {}).get('jobId')
            related = {identifier, turn.get('message', {}).get('job', {}).get('id')}
            for event in read_rows(path.parent / 'events.jsonl'):
                if event.get('turn') == turn['turn'] and event.get('receipt'):
                    related.add(event['receipt'].get('jobId'))
            for item in turn.get('approvals', []):
                related.add((item.get('result', {}).get('continuation') or {}).get('jobId'))
            cards = turn.get('message', {}).get('actions', []) + [item.get('result', {}) for item in turn.get('approvals', [])]
            related.update((card.get('job') or {}).get('id') for card in cards)
            related.discard(None)
            rows = turn_events(jobs, related, identifier)
            related = {r.get('jobId') or r.get('scope', {}).get('jobId') for r in rows}
            action_ids = {card.get('id') for card in cards} | {item['id'] for item in turn.get('approvals', [])}
            rows = sorted(rows + confirmed_commits(events, rows, action_ids), key=lambda r: r['time'])
            calls = [call for r in rows if r['kind'] == 'model_attempt_result' for call in r.get('toolCalls', [])]
            commits = [r for r in rows if r['kind'] == 'database_commit']
            # Old pre-v2 observer may list several flushes within one commit.
            # Durable IDs/revisions are reported separately from raw ORM events.
            durable = {(r['table'], r['values'].get('id'), r['values'].get('revision'), r['values'].get('state')) for r in commits}
            turns.append({'turn': turn['turn'], 'jobId': identifier, 'state': turn.get('message', {}).get('job', {}).get('state'), 'taskOutcome': turn.get('message', {}).get('job', {}).get('taskOutcome'), 'seconds': turn['seconds'], 'timing': timing.get(identifier, {}), 'associatedJobs': sorted(related), 'mainGraphModelAttempts': sum(r['kind'] == 'model_attempt_start' for r in rows), 'providerRequestsObserved': sum(r['kind'] == 'provider_request_start' for r in rows), 'modelIssuedTools': dict(Counter(c['name'] for c in calls)), 'dispatchedTools': dict(Counter(r['tool'] for r in rows if r['kind'] == 'tool_dispatch')), 'logicalNodes': sum(r['kind'] == 'tool_logical_node' for r in rows), 'actualToolAttempts': sum(r['kind'] == 'tool_attempt_start' for r in rows), 'committedRecords': len(durable), 'committedByTable': dict(Counter(x[0] for x in durable)), 'loops': candidates(rows), 'exception': turn.get('exception'), 'classification': 'awaiting-independent-semantic-review'})
            turns[-1]['searchProgress'] = search_progress(rows)
            turns[-1]['confirmationRequests'] = [{'actionId': item['id'], 'action': item['action'], 'authorizedTurn': item.get('authorizedTurn'), 'transport': 'HTTP POST business-actions/{id}/confirm', 'resultState': item.get('result', {}).get('state'), 'executionMode': item.get('result', {}).get('executionMode'), 'continuation': item.get('result', {}).get('continuation')} for item in turn.get('approvals', [])]
            turns[-1]['confirmationCount'] = len(turns[-1]['confirmationRequests'])
            turns[-1]['fullModeConfirmationNeedsReview'] = value['case']['mode'] == 'full' and bool(turns[-1]['confirmationCount'])
            turns[-1]['pendingActions'] = [{'actionId': card['id'], 'action': card['action'], 'canConfirm': card.get('canConfirm')} for card in cards if card.get('state') == 'pending']
        downloads = [inspect_file(item) for turn in value['turns'] for item in turn.get('files', [])]
        results.append({'case': value['case']['id'], 'role': value['case']['role'], 'effort': value['case']['effort'], 'permissionMode': value['case']['mode'], 'plannedTurns': len(value['case']['turns']), 'observedTurns': len(turns), 'turns': turns, 'downloads': downloads, 'evidence': str(path)})
    scripts = {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest() for name in ('report.py', 'downloads.py', 'loops.py')}
    return {'analysisScripts': scripts, 'casesObserved': len(results), 'turnsObserved': sum(len(r['turns']) for r in results), 'caseResults': results, 'loopCandidates': [candidate for result in results for turn in result['turns'] for candidate in turn['loops']], 'countsAreNotSuccess': True}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--results', required=True)
    p.add_argument('--trace', required=True)
    p.add_argument('--worker-log', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    target = Path(args.output)
    if target.exists():
        raise RuntimeError('Refusing to overwrite evidence summary')
    target.write_text(json.dumps(summarize(Path(args.results), Path(args.trace), Path(args.worker_log)), ensure_ascii=False, indent=2, default=str))
