"""Explicit, offline checks for denied reads and committed field reconstruction."""
from copy import deepcopy
from .evidence import read, ROOT, digest
from .facts import no_mutations, mutations


def check():
    base = {'turns': [{'receipt': {'jobId': 'j'}}], 'trace': [
        {'kind': 'commit_observation_start', 'jobId': 'j', 'protocol': 1, 'captureId': 'c'},
        {'kind': 'commit_observation_end', 'jobId': 'j', 'protocol': 1, 'captureId': 'c', 'commits': [], 'unsupported': []}]}
    assert no_mutations(base, 'weekly')[0] == 'PASS'
    assert no_mutations({'turns': [], 'trace': []}, 'weekly')[0] == 'INCOMPLETE'
    missing = deepcopy(base); missing['trace'].pop()
    assert no_mutations(missing, 'weekly')[0] == 'INCOMPLETE'
    for entity, tables in [('work', ['company_work_item', 'company_work_update', 'company_work_material', 'company_work_revision']), ('weekly', ['company_report', 'company_report_revision'])]:
        for table in tables:
            value = deepcopy(base); value['trace'].append({'kind': 'database_commit', 'table': table})
            assert no_mutations(value, entity)[0] == 'FAIL'
    fixture = read(ROOT / 'artifacts/agent-eval/spec082-acceptance-v2/transient-unauthorized.json')
    case, result = fixture['case'], fixture['result']
    def fields(value):
        return next(r['status'] for r in mutations(case, value, 0, 'work', 'work') if r['id'].endswith('authorized-fields'))
    assert fields(result) == 'FAIL'
    case = deepcopy(case)
    case['input']['allowedFields'][0]['work'] = ['title', 'status']
    missing = deepcopy(result)
    for item in missing['before']['work']['items']:
        item.pop('content', None)
    assert fields(missing) == 'INCOMPLETE'
    gap = deepcopy(result)
    first = next(e for e in gap['trace'] if e.get('kind') == 'database_commit' and e.get('table') == 'company_work_item')
    first['values'].pop('content', None)
    for end in gap['trace']:
        if end.get('kind') != 'commit_observation_end':
            continue
        rows = [e for e in gap['trace'] if e.get('kind') == 'database_commit' and e.get('captureId') == end['captureId']]
        end['commits'] = [{'transactionId': tx, 'rows': len([e for e in rows if e['transactionId'] == tx]),
                          'sha256': digest([{k: e[k] for k in ('operation', 'table', 'values', 'scope')} for e in rows if e['transactionId'] == tx])}
                         for tx in dict.fromkeys(e['transactionId'] for e in rows)]
    assert fields(gap) == 'INCOMPLETE'
    source = ROOT / 'artifacts/agent-eval/spec082-followup-offline-fields'
    manifest = read(source / 'manifest.json')
    report_case = next(c for c in manifest['cases'] if c['id'] == 'local/weekly')
    report_result = read(source / 'trials/s0013/result.json')
    def report_bounds(value):
        return next(r['status'] for r in mutations(report_case, value, 1, 'weekly', 'report') if r['id'].endswith('-bounds'))
    assert report_bounds(report_result) == 'PASS'
    child = next(e['jobId'] for e in report_result['trace'] if e.get('kind') == 'commit_observation_start' and e.get('jobKind') == 'report')
    absent = deepcopy(report_result)
    absent['trace'] = [e for e in absent['trace'] if not (e.get('kind') == 'commit_observation_end' and e.get('jobId') == child)]
    assert report_bounds(absent) == 'INCOMPLETE'
    extra = deepcopy(report_result)
    template = next(e for e in extra['trace'] if e.get('kind') == 'database_commit' and e.get('jobId') == child and e.get('table') == 'company_report')
    for operation in ('insert', 'delete'):
        event = deepcopy(template)
        event.update(operation=operation, transactionId='extra-' + operation)
        event['values'].update(id='unauthorized-extra-report', revision=1, deleted=operation == 'delete')
        extra['trace'].append(event)
    for end in extra['trace']:
        if end.get('kind') != 'commit_observation_end' or end.get('jobId') != child:
            continue
        rows = [e for e in extra['trace'] if e.get('kind') == 'database_commit' and e.get('captureId') == end['captureId']]
        end['commits'] = [{'transactionId': tx, 'rows': len([e for e in rows if e['transactionId'] == tx]),
                          'sha256': digest([{k: e[k] for k in ('operation', 'table', 'values', 'scope')} for e in rows if e['transactionId'] == tx])}
                         for tx in dict.fromkeys(e['transactionId'] for e in rows)]
    assert report_bounds(extra) == 'FAIL'
    print('PASS: denied read zero-write proof; all entity subrecords; missing capture; transient unauthorized change; absent initial content; report child extra create-delete and missing capture')


if __name__ == '__main__':
    check()
