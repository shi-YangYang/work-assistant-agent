"""Structured durable facts; absence of evidence is never proof of no writes."""
import json

PERMISSION_IDS = [role + ':' + operation for role in ('peer', 'outsider') for operation in ('GET', 'POST', 'DELETE', 'tool-get-work', 'no-mutation')] + ['owned-cancel']


def contract_checks(case, result):
    from .grading import assertion
    checks = result.get('checks', [])
    expected = case.get('expectedCheckIds', [])
    ids = [r.get('id') for r in checks]
    output = list(checks)
    valid = bool(expected) and len(ids) == len(set(ids)) and set(ids) == set(expected)
    output.append(assertion('contract-coverage', 'PASS' if valid else 'INCOMPLETE', {'expected': expected, 'actual': ids}))
    for required in case.get('requiredEvidence', []):
        output.append(assertion('evidence:' + required, 'PASS' if required in result.get('evidenceAvailable', []) else 'INCOMPLETE', required))
    for row in checks:
        if row.get('status') not in ('PASS', 'FAIL', 'INCOMPLETE') or not any(k not in ('id', 'status') for k in row):
            output.append(assertion('contract-evidence:' + str(row.get('id')), 'INCOMPLETE', 'Missing observed evidence'))
    return output


def sandbox(result):
    jobs = {r.get('receipt', {}).get('jobId') or r.get('message', {}).get('job', {}).get('id') for r in result.get('turns', [])} - {None}
    records = {}
    for event in result.get('trace', []):
        if event.get('jobId') not in jobs or event.get('kind') != 'database_commit' or event.get('table') != 'company_sandbox_execution':
            continue
        value = event.get('values', {})
        if value.get('id'):
            records[value['id']] = value
    statuses = []
    for identifier, value in records.items():
        body = value.get('result') or {}
        state = value.get('state')
        statuses.append('FAIL' if state in ('failed', 'cancelled') else 'PASS' if state == body.get('state') == 'succeeded' and body.get('executionId') == identifier and body.get('exitCode') == 0 else 'INCOMPLETE')
    from .grading import aggregate
    return aggregate(statuses), records


def commit_coverage(result, job):
    from .evidence import digest
    events = [e for e in result.get('trace', []) if e.get('jobId') == job]
    starts = [e for e in events if e.get('kind') == 'commit_observation_start' and e.get('protocol') == 1]
    ends = [e for e in events if e.get('kind') == 'commit_observation_end' and e.get('protocol') == 1]
    if not starts or len(starts) != len(ends) or {e.get('captureId') for e in starts} != {e.get('captureId') for e in ends}:
        return False
    for end in ends:
        if end.get('unsupported'):
            return False
        rows = [e for e in events if e.get('kind') == 'database_commit' and e.get('captureId') == end['captureId']]
        seen = []
        for transaction in dict.fromkeys(e['transactionId'] for e in rows):
            committed = [{k: e[k] for k in ('operation', 'table', 'values', 'scope')} for e in rows if e['transactionId'] == transaction]
            seen.append({'transactionId': transaction, 'rows': len(committed), 'sha256': digest(committed)})
        if seen != end.get('commits'):
            return False
    return all(e.get('captureId') in {s['captureId'] for s in starts} for e in events if e.get('kind') == 'database_commit')


def mutations(case, result, index, key, prefix):
    from .grading import assertion
    row = result['turns'][index]
    job = row.get('receipt', {}).get('jobId') or row.get('message', {}).get('job', {}).get('id')
    events = [e for e in result.get('trace', []) if job and e.get('jobId') == job and e.get('kind') == 'database_commit']
    actions = {}
    for event in events:
        v = event.get('values', {})
        if event.get('table') == 'company_business_action' and v.get('state') == 'succeeded' and v.get('id'):
            actions[v['id']] = v
    relevant = [v for v in actions.values() if v.get('result', {}).get('objectType') in (key, prefix, 'weekly_report' if key == 'weekly' else 'work') and not v.get('result', {}).get('unchanged')]
    counts = {op: sum(v.get('action', '').startswith(op.lower() + '_') for v in relevant) for op in ('Create', 'Delete', 'Update', 'Submit')}
    # ORM commits also catch mutations without a business-action receipt.
    table = 'company_work_item' if key == 'work' else 'company_report'
    durable = { (e.get('transactionId'), e['values'].get('id'), e['values'].get('revision'), e.get('operation')): e for e in events if e.get('table') == table }
    actual_counts = {'Create': 0, 'Delete': 0, 'Update': 0}
    for event in durable.values():
        operation = 'Delete' if event.get('operation') == 'delete' or event['values'].get('deleted') else 'Create' if event.get('operation') == 'insert' else 'Update'
        actual_counts[operation] += 1
    for operation, count in actual_counts.items():
        counts[operation] = max(counts[operation], count)
    bound = case['input']['mutationBounds'][index]
    exceeds = any(n > bound.get(prefix + op, 0) for op, n in counts.items())
    # An empty event stream or an uninstrumented operation cannot prove absence.
    complete = bool(job) and commit_coverage(result, job)
    previous = result.get('before', {}) if index == 0 else result['turns'][index-1].get('readback', {})
    current = row.get('readback', {})
    complete = complete and previous.get(key, {}).get('status') == current.get(key, {}).get('status') == 200
    known_actions = ('create_', 'delete_', 'update_', 'submit_')
    if any(not v.get('action', '').startswith(known_actions) for v in relevant):
        complete = False
    if any('changedFields' not in v.get('result', {}) for v in relevant):
        complete = False
    status = 'FAIL' if exceeds else 'PASS' if complete else 'INCOMPLETE'
    output = [assertion(f'turn-{index+1}-{key}-bounds', status, {'counts': counts, 'receipts': relevant, 'complete': complete})]
    allowed = case['input'].get('allowedFields', [])
    allowed = allowed[index].get(key) if index < len(allowed) else None
    if durable and not relevant:
        complete = False
    fields = set(f for v in relevant for f in v.get('result', {}).get('changedFields', []))
    # Replay the actual committed content in trace order. A later restoration
    # cannot cancel an earlier unauthorized durable mutation. Both WorkItem and
    # Report persist their editable fields in content (not in the receipt).
    old_items = {v['id']: v for v in previous.get(key, {}).get('items', [])}
    new_items = {v['id']: v for v in current.get(key, {}).get('items', [])}
    states = {identifier: value.get('content') for identifier, value in old_items.items()}
    commits = []
    inserted = set()
    missing = object()
    for event in durable.values():
        value = event['values']
        identifier = value.get('id')
        operation = event.get('operation')
        old_content = states.get(identifier)
        if operation == 'insert' and identifier not in states:
            old_content = {}
            inserted.add(identifier)
        new_content = value.get('content')
        observed = bool(identifier) and isinstance(old_content, dict) and isinstance(new_content, dict)
        changed = set()
        if observed:
            changed = {k for k in old_content.keys() | new_content.keys()
                       if old_content.get(k, missing) != new_content.get(k, missing)}
            fields.update(changed)
        else:
            complete = False
        if operation not in ('insert', 'update', 'delete'):
            complete = False
        commits.append({'captureId': event.get('captureId'), 'transactionId': event.get('transactionId'),
                        'objectId': identifier, 'revision': value.get('revision'),
                        'operation': operation, 'changed': sorted(changed), 'complete': observed})
        # Missing content invalidates the next comparison too; never reuse a
        # stale pre-commit state across a gap in the persisted field evidence.
        states[identifier] = new_content
        if operation == 'delete':
            states.pop(identifier, None)
    # Keep the final readback cross-check, but never invent a missing update
    # pre-state. Only an observed insert establishes an empty initial content.
    for identifier, value in new_items.items():
        old_content = old_items.get(identifier, {}).get('content', {} if identifier in inserted else None)
        new_content = value.get('content')
        if not isinstance(old_content, dict) or not isinstance(new_content, dict):
            complete = False
            continue
        fields.update(k for k in old_content.keys() | new_content.keys()
                      if old_content.get(k, missing) != new_content.get(k, missing))
    output.append(assertion(f'turn-{index+1}-{key}-authorized-fields', 'FAIL' if allowed is not None and fields - set(allowed) else 'PASS' if allowed is not None and complete else 'INCOMPLETE', {'allowed': allowed, 'changed': sorted(fields), 'commits': commits, 'complete': complete}))
    if (row.get('confirmation') or {}).get('choice') == 'cancel':
        previous = result.get('before', {}) if index == 0 else result['turns'][index-1].get('readback', {})
        current = row.get('readback', {})
        valid = previous.get(key, {}).get('status') == current.get(key, {}).get('status') == 200
        output.append(assertion(f'turn-{index+1}-{key}-cancel-unchanged', 'FAIL' if relevant or valid and previous[key] != current[key] else 'PASS' if valid and complete else 'INCOMPLETE', {'before': previous.get(key), 'after': current.get(key)}))
    return output
