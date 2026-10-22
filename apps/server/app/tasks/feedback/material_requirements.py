"""Persist selected file identities and cover them only with owned write receipts."""
from copy import deepcopy

from app.core.digests import digest


def source_key(source):
    return digest(source)


def collections(job):
    previous = job.result.get('taskSnapshot', {}).get('previousTask', {})
    inherited = previous.get('materialCollections', []) if job.result.get('taskSnapshot', {}).get('relation') == 'continue' else []
    return list({item['id']: item for item in [*inherited, *job.result.get('materialCollections', [])]}.values())


def remember(job, selection, *, item_id=''):
    values = collections(job)
    if not selection.get('continued'):
        selection = {**selection, 'id': digest({'selection': selection['id'], 'taskItemId': item_id})}
    old = next((item for item in values if item['id'] == selection['id']), {})
    if old and {source_key(source) for source in old['sources']} != {source_key(source) for source in selection['sources']}:
        selection = {**selection, 'sources': old['sources']}
    if old.get('targetId'):
        selection = {**selection, 'targetId': old['targetId'], 'destination': 'existing'}
    value = {**selection, 'taskItemIds': list(dict.fromkeys([*selection.get('taskItemIds', []),
        *old.get('taskItemIds', []), *([item_id] if item_id else [])]))}
    value.pop('continued', None)
    job.result = {**job.result, 'materialCollections': [item for item in values if item['id'] != value['id']] + [value]}
    return value


def settle(job, card):
    """A successful create binds its own remaining files to the created work."""
    if card.get('state') != 'succeeded' or card.get('action') != 'create_work' or not card.get('objectId'):
        return
    values = collections(job)
    job.result = {**job.result, 'materialCollections': [
        {**item, 'destination': 'existing', 'targetId': card['objectId'], 'title': card.get('title', ''),
         'destinationProof': {'source': 'receipt', 'receiptId': card['id']}}
        if item['destination'] == 'new' and card.get('taskItemId') in item.get('taskItemIds', [])
        else item for item in values]}


def uncovered(selection, cards, *, include_pending=False):
    expected = {source_key(source): source for source in selection['sources']}
    for card in cards:
        if card.get('taskItemId') not in selection.get('taskItemIds', []):
            continue
        if selection.get('targetId') and card.get('objectId', card.get('preview', {}).get('targetId')) != selection['targetId']:
            continue
        if card.get('state') == 'succeeded':
            sources = card.get('materialSources', [])
        elif include_pending and card.get('state') == 'pending' and card.get('canConfirm'):
            sources = card.get('materialSources', [])
        else:
            continue
        for source in sources:
            expected.pop(source_key(source), None)
    return list(expected.values())


def remaining(job, cards, *, include_pending=False):
    return [{'selectionId': item['id'], 'targetId': item.get('targetId', ''),
             'title': item.get('title') or '所选工作', 'fields': ['materials'],
             **({'missingTarget': True} if item['destination'] == 'unselected' else {}),
             'missingMaterials': missing}
            for item in collections(job)
            if (missing := uncovered(item, cards, include_pending=include_pending))]


def snapshot(job):
    return deepcopy(collections(job))
