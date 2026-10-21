"""Read scopes derived from committed tool results, never model declarations.

A write can make a previously sufficient answer stale. Its receipt opens only
the affected data family and objects returned by subsequent scoped queries.
This bounds a follow-up episode; it does not decide semantic necessity.
"""
from app.modules.team.sources import canonical_token

READS = {
    'work': frozenset({'find_work_items', 'get_work_item', 'list_work_updates', 'list_work_materials', 'read_work_material'}),
    'report': frozenset({'query_reports', 'query_report_obligations'}),
    'deliverable': frozenset({'read_deliverable', 'inspect_table'}),
}
TEAM_READS = frozenset({'query_team_business', 'read_team_source'})
FILE_WRITES = frozenset({'generate_image', 'run_python', 'export_table', 'create_chart', 'create_document', 'create_slides'})


def changes(call, result):
    """Recognize actual versioned effects, not a generic successful tool call."""
    name, args = call['name'], call.get('args', {})
    if result.get('state') != 'succeeded' or result.get('executed') is False or result.get('changed') is False:
        return []
    if name == 'execute_business_action':
        action = args.get('action')
        if not result.get('id') or result.get('action') != action:
            return []
        family = 'work' if action in ('create_work', 'update_work', 'delete_work') else 'report' if action in ('generate_report', 'edit_report', 'submit_report', 'delete_report') else None
        if not family:
            return []
        if action.startswith('delete_'):
            identifier = args.get('target_id')
            return [{'family': family, 'id': identifier, 'deleted': True, 'receipt': result['id']}] if identifier else []
        if result.get('objectType') != family:
            return []
        identifier, revision = result.get('objectId'), result.get('objectRevision')
        expected = args.get('expected_revision', 0)
    elif name in ('propose_progress', 'propose_followup'):
        if result.get('status') != 'confirmed' or not result.get('draftId') or result.get('objectType') != 'work':
            return []
        identifier, revision = result.get('objectId'), result.get('objectRevision')
        expected, family = 0, 'work'
    elif name == 'save_deliverable' or name in FILE_WRITES:
        delivery = result if name == 'save_deliverable' else result.get('delivery', {})
        identifier, revision = delivery.get('id'), delivery.get('revision')
        expected, family = args.get('expected_revision', 0), 'deliverable'
    else:
        return []
    # Middleware retains raw model arguments even when the registered tool's
    # Pydantic schema coerces a numeric string. Never fail after a committed write.
    if isinstance(expected, str):
        try:
            expected = int(expected)
        except ValueError:
            return []
    if type(expected) is not int or not isinstance(identifier, str) or not identifier or type(revision) is not int or revision <= max(0, expected):
        return []
    return [{'family': family, 'id': identifier, 'revision': revision}]


def capture(call, result, prior_calls):
    candidates = changes(call, result)
    # Image batches preserve each committed result; partial/failed siblings do
    # not gain authority from another picture's success.
    if call['name'] == 'generate_image' and isinstance(result.get('results'), list):
        candidates = [effect for item in result['results'] if isinstance(item, dict) for effect in changes(call, item)]
    known = [effect for row in prior_calls.values() for effect in row.get('changes', [])]
    return [effect for effect in candidates if effect not in known]


def scope(changes):
    result = {}
    for effect in changes:
        identifiers = result.setdefault(effect['family'], [])
        if not effect.get('deleted') and effect['id'] not in identifiers:
            identifiers.append(effect['id'])
    return result


def available(row):
    if row.get('used'):
        return set()
    families = row.get('readScope', {})
    names = set().union(*(READS[family] for family in families if family in READS))
    return names | (TEAM_READS if families.keys() & {'work', 'report'} else set())


def team_source(row, args, access):
    raw = args.get('token')
    token = canonical_token(raw) if isinstance(raw, str) else ''
    source = row.get('teamSources', {}).get(token, {})
    evidence = (access or {}).get('reads', {}).get(token, {})
    if source.get('family') not in row.get('readScope', {}) or not evidence:
        return None
    child = args.get('child_id')
    if child and (not isinstance(child, str) or child not in source.get('children', {})):
        return None
    return token, source, evidence


def permits(row, call, access=None):
    if call['name'] not in available(row):
        return False
    name, args, scopes = call['name'], call.get('args', {}), row['readScope']
    if name == 'query_team_business':
        kind = args.get('kind', 'work')
        return isinstance(kind, str) and kind in scopes
    if name == 'read_team_source':
        return team_source(row, args, access) is not None
    if name == 'find_work_items':
        return 'work' in scopes
    if name in READS['work']:
        return args.get('work_id') in scopes.get('work', [])
    if name == 'query_report_obligations':
        return 'report' in scopes
    if name == 'query_reports':
        return not args.get('report_id') or args['report_id'] in scopes.get('report', [])
    if name == 'read_deliverable':
        return not args.get('deliverable_id') or args['deliverable_id'] in scopes.get('deliverable', [])
    if name == 'inspect_table':
        source = args.get('source')
        reference = source.get('input_ref') if isinstance(source, dict) else None
        return isinstance(reference, dict) and reference.get('deliverable_id') in scopes.get('deliverable', []) and not reference.get('attachment_id')
    return False


def remember_team_source(row, item, family, access):
    """Keep source pointers only; live access owns identity/version/parent facts."""
    if not isinstance(item, dict) or item.get('kind') != 'business':
        return
    token = item.get('token')
    if not isinstance(token, str) or not token:
        return
    evidence = (access or {}).get('reads', {}).get(token, {})
    if (not evidence or item.get('objectType') != evidence.get('type') or
            item.get('objectId') != evidence.get('id') or
            item.get('ownerId') != evidence.get('ownerId') or
            type(item.get('revision')) is not int or item['revision'] != evidence.get('version')):
        return
    sources = row.setdefault('teamSources', {})
    source = sources.setdefault(token, {'family': family, 'children': {}})
    if source['family'] != family:
        return
    # These are structured edges returned by the authorized reader, never IDs
    # found in body text or every reference already present in the job's access.
    if item['objectType'] in ('work', 'report'):
        source['children'].update({identifier: 'message' for identifier in item.get('sourceMessageIds', [])
                                   if isinstance(identifier, str) and identifier})
    if item['objectType'] in ('work', 'message'):
        source['children'].update({child['id']: 'document' for child in item.get('attachments', [])
                                   if isinstance(child, dict) and child.get('kind') == 'document'
                                   and isinstance(child.get('id'), str) and child['id']})
    return evidence


def extend_team(row, call, result, access):
    if call['name'] == 'query_team_business':
        family = call.get('args', {}).get('kind', 'work')
        if family not in row.get('readScope', {}):
            return
        for item in result.get('items', []):
            if not isinstance(item, dict) or item.get('objectType') != family:
                continue
            evidence = remember_team_source(row, item, family, access)
            if evidence and evidence['id'] not in row['readScope'][family]:
                row['readScope'][family].append(evidence['id'])
        return
    parent = team_source(row, call.get('args', {}), access)
    if parent is None:
        return
    token, source, evidence = parent
    child = call.get('args', {}).get('child_id')
    returned = (access or {}).get('reads', {}).get(result.get('token'), {})
    if child:
        if (result.get('objectId') != child or result.get('objectType') != source['children'][child]
                or returned.get('parent') != evidence or returned.get('ownerId') != evidence.get('ownerId')):
            return
    elif result.get('token') != token:
        return
    remember_team_source(row, result, source['family'], access)


def extend(row, call, result, access=None):
    """Only successful directory rows extend the same family's object scope.

    Team detail expansion follows only actual parent/child source references.
    Tool authorization and version checks still validate each subsequent read.
    """
    if call['name'] in TEAM_READS:
        extend_team(row, call, result, access)
        return
    if call['name'] == 'query_report_obligations' and 'report' in row.get('readScope', {}):
        # Obligation IDs identify schedules, not reports. Their explicit report
        # links permit a live read only; this directory supplies no revision.
        for item in result.get('items', []):
            identifier = item.get('reportId') if isinstance(item, dict) else None
            if isinstance(identifier, str) and identifier and identifier not in row['readScope']['report']:
                row['readScope']['report'].append(identifier)
        return
    family = ('work' if call['name'] == 'find_work_items' else
              'report' if call['name'] == 'query_reports' else
              'deliverable' if call['name'] == 'read_deliverable' and not call['args'].get('deliverable_id') else None)
    if family not in row.get('readScope', {}):
        return
    for item in result.get('items', []):
        if isinstance(item, dict) and isinstance(item.get('id'), str) and type(item.get('revision')) is int:
            if item['id'] not in row['readScope'][family]:
                row['readScope'][family].append(item['id'])
