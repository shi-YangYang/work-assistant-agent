"""Server-issued atomic task identities, independent of rewritten tool arguments."""


def collect(job):
    snapshot = job.result.get('taskSnapshot', {})
    previous = snapshot.get('previousTask', {}).get('items', []) if snapshot.get('relation') == 'continue' else []
    current = job.result.get('taskItems', [])
    return list({item['id']: item for item in [*previous, *current]}.values())[-32:]


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
