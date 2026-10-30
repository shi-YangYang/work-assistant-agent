"""Versioned, no-I/O-to-provider catalog and frozen execution plans."""
import copy
import subprocess
from .evidence import BASE, ROOT, digest, fingerprint, read, seal


def catalog():
    data = read(BASE / 'catalog.json')
    if data['version'] != 1:
        raise ValueError('Unsupported catalog')
    ids = set()
    for case in data['cases']:
        if case['id'] in ids or not case['requirements'] or not case['assertions']:
            raise ValueError('Duplicate ID or missing expectation')
        ids.add(case['id'])
        if case['execution'] not in ('real-model', 'real-browser', 'contract/replay'):
            raise ValueError('Invalid execution level')
        source = ROOT / case['source']['file']
        rows = read(source)
        if not any(row['id'] == case['source']['id'] for row in rows):
            raise ValueError('Unresolved source: ' + case['id'])
    return data


def plan(suite, config):
    cat = catalog()
    suites = read(BASE / 'suites.json')['suites']
    selected = suites[suite]
    if set(config) != {'models', 'environment', 'timeoutSeconds', 'comparison'}:
        raise ValueError('Config requires models/environment/timeoutSeconds/comparison only')
    if not config['models'] or not 1 <= config['timeoutSeconds'] <= 1860:
        raise ValueError('Invalid timeout or model configuration')
    for model in config['models']:
        if set(model) != {'id', 'provider', 'model', 'parameters', 'effort'} or model['effort'] not in ('low', 'high'):
            raise ValueError('Explicit actual low/high model parameters required')
    cases = []
    for item in cat['cases']:
        if item['id'] not in selected['cases']:
            continue
        case = copy.deepcopy(item)
        case['input'] = next(c for c in read(ROOT / case['source']['file']) if c['id'] == case['source']['id'])
        case['materials'] = {name: {'base64': __import__('base64').b64encode((BASE / 'cases/materials' / name).read_bytes()).decode()} for name in case['input'].get('attachments', [])}
        cases.append(case)
    if set(selected['cases']) != {c['id'] for c in cases}:
        raise ValueError('Unknown suite member')
    slots = [{'id': f's{index:04}', 'caseId': c['id'], 'model': m, 'trial': trial, 'required': True}
             for index, (c, m, trial) in enumerate(((c, m, trial) for c in cases for m in config['models'] for trial in range(1, c.get('repetitions', 1) + 1)), 1)]
    return seal({'version': 1, 'suite': suite, 'cases': cases, 'slots': slots, 'config': config,
                 'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                 'source': fingerprint(), 'catalogSha256': digest(cat), 'gradingVersion': 1,
                 'concurrency': 1, 'implicitProviderCalls': 0})
