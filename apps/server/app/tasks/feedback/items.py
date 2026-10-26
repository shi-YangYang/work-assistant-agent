"""Server-issued atomic task identities, independent of rewritten tool arguments."""


def collect(job):
    snapshot = job.result.get('taskSnapshot', {})
    previous = snapshot.get('previousTask', {}).get('items', []) if snapshot.get('relation') == 'continue' else []
    current = job.result.get('taskItems', [])
    items = {item['id']: item for item in [*previous, *current]}
    def audit_alias(item):
        recovered = item.get('recoveredSchemaFailure') or {}
        executed = items.get(item.get('recoveredBy'))
        return (executed and executed['id'] != item['id']
                and item.get('action') == executed.get('action') == 'update_work'
                and item.get('targetId') == executed.get('targetId')
                and item.get('state') == executed.get('state') == 'succeeded'
                and recovered.get('receiptId')
                and recovered['receiptId'] == item.get('receiptId') == executed.get('receiptId'))
    # Keep the superseded attempt in the job audit, not as a second completed
    # operation (its original fields may include explicitly preserved content).
    return [item for item in items.values() if not audit_alias(item)][-32:]


def record(job, item_id, result):
    if not item_id:
        return
    items = collect(job)
    item = next((item for item in items if item['id'] == item_id), None)
    if item:
        item = {**item, 'state': result.get('state') or result.get('status', 'proposed')}
        if result.get('id') or result.get('draftId'):
            item['receiptId'] = result.get('id') or result['draftId']
        job.result = {**job.result, 'taskItems': [entry for entry in job.result.get('taskItems', []) if entry['id'] != item_id] + [item]}
