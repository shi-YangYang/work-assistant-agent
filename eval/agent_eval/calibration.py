"""Explicit real offline calibration, or evidence-only replay without new calls."""
from pathlib import Path
from .evidence import BASE, read, write, digest
from .grading import semantic, configured_grader, evidence_surface, parse_evidence_grade


async def calibrate(args):
    catalog = read(BASE / 'calibration.json')
    selected = set(args.ids.split(',')) if args.ids else {s['id'] for s in catalog['samples']}
    if selected - {s['id'] for s in catalog['samples']}:
        raise ValueError('Unknown calibration sample')
    samples = [s for s in catalog['samples'] if s['id'] in selected]
    output = Path(args.output)
    configured = None if args.replay else await configured_grader(args.source_user)
    write(output / 'manifest.json', {'version': 2, 'mode': 'evidence-replay' if args.replay else 'real-offline-model',
          'sampleIds': [s['id'] for s in samples], 'catalogSha256': digest(catalog),
          'graderSha256': digest((BASE / 'grading.py').read_text()), 'labelProvenance': catalog['labelProvenance'],
          'humanApproval': False, 'replayedFrom': args.replay})
    results = []
    for sample in samples:
        write(output / 'started' / (sample['id'] + '.json'), {'sample': sample, 'providerCallPlanned': not bool(args.replay)})
        if args.replay:
            prior = read(Path(args.replay) / (sample['id'] + '.json'))
            if prior['sample'] != sample:
                raise ValueError('Calibration replay sample differs')
            actual = prior['actualModelGrade']
            if actual.get('version') != 2:
                raise ValueError('Historical quote-contract grades require their historical parser')
            if actual.get('raw'):
                verdicts = parse_evidence_grade(actual['raw'], sample['requirements'], evidence_surface(sample['actual']))
                if verdicts != actual.get('requirements'):
                    raise ValueError('Replay verdict differs from stored evidence')
        else:
            actual = await semantic(sample['requirements'], sample['actual'], args.source_user, configured)
        observed = [r['status'] for r in actual.get('requirements', [])]
        matches = bool(observed) and all(v == sample['expected'] for v in observed)
        record = {'sample': sample, 'actualModelGrade': actual, 'matchesReference': matches,
                  'referenceLabelSource': catalog['labelProvenance'], 'humanApproval': False, 'replayedFrom': args.replay}
        write(output / (sample['id'] + '.json'), record)
        results.append({'id': sample['id'], 'matchesReference': matches, 'status': actual['status']})
    write(output / 'summary.json', {'samples': results, 'newProviderCalls': 0 if args.replay else len(samples), 'humanApproval': False})
    return results
