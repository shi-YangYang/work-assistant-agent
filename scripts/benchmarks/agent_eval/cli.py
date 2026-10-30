"""Local/manual entry point. Catalog/plan/check never import application runtime."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from .evidence import BASE, read, write, seal, verify, digest, fingerprint, grader_source, verify_files
from .contracts import catalog, plan


def stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')


async def run(args):
    from .adapters import environment, execute
    from .cancellation import bounded_trial
    manifest = verify(read(args.plan))
    if manifest['source'] != fingerprint():
        raise ValueError('Source drift; freeze a new plan')
    _, metadata, _ = environment(args.metadata)
    if metadata['schema'] != manifest['config']['environment']['schema']:
        raise ValueError('Environment differs from frozen plan')
    trace = Path(args.metadata).parent / 'trace.jsonl'
    starts = [json.loads(line) for line in trace.read_text().splitlines() if json.loads(line).get('kind') == 'runtime_start'] if trace.exists() else []
    import hashlib, subprocess
    app_diff = hashlib.sha256(subprocess.check_output(['git', 'diff', '--', 'apps', 'packages'])).hexdigest()
    for service in ('api', 'worker'):
        matches = [row for row in starts if row.get('service') == service]
        if matches and matches[-1].get('scriptSha256', {}).get('trace.py') != hashlib.sha256((BASE.parent.parent / 'company/web-acceptance/agent-audit/trace.py').read_bytes()).hexdigest():
            raise ValueError('Loaded commit observer differs; restart the owned API/worker before a new run')
        if not matches or matches[-1]['applicationCommit'] != manifest['commit'] or matches[-1]['appDiffSha256'] != app_diff or not isinstance(matches[-1].get('applicationSource'), list) or {r['path']: r['sha256'] for r in matches[-1].get('applicationSource', [])} != {k: v for k, v in manifest['source'].items() if k.startswith(('apps/', 'packages/'))}:
            raise ValueError('Missing/mismatched loaded runtime provenance: ' + service)
    root = Path(args.output)
    marker = root / 'manifest.json'
    if marker.exists():
        if read(marker) != manifest:
            raise ValueError('Refusing different plan in existing run')
    else:
        write(marker, manifest)
    import signal
    stopped = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stopped.set)
    selected = set(args.slots.split(',')) if args.slots else {s['id'] for s in manifest['slots']}
    if selected - {s['id'] for s in manifest['slots']}:
        raise ValueError('Unknown execution slot')
    for slot in manifest['slots']:
        if slot['id'] not in selected:
            continue
        if stopped.is_set() or (root / 'STOP').exists():
            write(root / ('interruption-' + stamp() + '.json'), {'reason': 'Stop requested; current owned trial settled; unstarted slots retained'})
            break
        if manifest['source'] != fingerprint():
            raise ValueError('Source drift during run; stopped before next trial')
        directory = root / 'trials' / slot['id']
        if (directory / 'started.json').exists():
            continue
        write(directory / 'started.json', {'slot': slot, 'time': stamp()})
        case = next(c for c in manifest['cases'] if c['id'] == slot['caseId'])
        try:
            result = await bounded_trial(execute(case, slot, directory, args.metadata, args.materials, manifest['config']['timeoutSeconds']), stopped, manifest['config']['timeoutSeconds'], directory)
        except Exception as error:
            result = {'error': type(error).__name__, 'execution': 'INCOMPLETE', 'turns': []}
        write(directory / 'result.json', seal(result))
        print(json.dumps({'slot': slot['id'], 'case': slot['caseId'], 'error': result.get('error'), 'seconds': result.get('seconds')}), flush=True)


async def grade(args):
    from .grading import deterministic, semantic, semantic_payload, configured_grader
    root = Path(args.run)
    manifest = verify(read(root / 'manifest.json'))
    configured = await configured_grader(args.source_user) if args.mode == 'model' else None
    selected = set(args.slots.split(',')) if args.slots else {s['id'] for s in manifest['slots']}
    if selected - {s['id'] for s in manifest['slots']}:
        raise ValueError('Unknown grading slot')
    grading_id = stamp()
    write(root / 'grading-runs' / (grading_id + '.json'), {'version': 1, 'mode': args.mode, 'source': grader_source(), 'slots': [s for s in manifest['slots'] if s['id'] in selected], 'model': {k: configured[1][k] for k in ('base', 'model', 'choice')} if configured else None, 'rubricPlanSha256': manifest['sha256']})
    for slot in manifest['slots']:
        if slot['id'] not in selected:
            continue
        case = next(c for c in manifest['cases'] if c['id'] == slot['caseId'])
        path = root / 'trials' / slot['id'] / 'result.json'
        result = verify(read(path)) if path.exists() else None
        verify_files(result, path.parent, case.get('requiredEvidence', []))
        hard = deterministic(case, result)
        requirements, payload = semantic_payload(case, result)
        sem = await semantic(requirements, payload, args.source_user, configured) if args.mode == 'model' and result and result.get('turns') else {'status': 'INCOMPLETE', 'reason': 'No actual output or deterministic-only mode'}
        write(root / 'grades' / (slot['id'] + '-' + stamp() + '.json'), {'version': 1, 'gradingRun': grading_id, 'slot': slot['id'], 'evidenceSha256': digest(result), 'graderSha256': digest(grader_source()), 'requirementsSha256': digest(case['requirements']), 'assertions': hard, 'semantic': sem})
        print(slot['id'], 'graded', flush=True)


def review(args):
    root = Path(args.run)
    manifest = verify(read(root / 'manifest.json'))
    for row in read(args.decisions):
        slot = next(s for s in manifest['slots'] if s['id'] == row['slot'])
        case = next(c for c in manifest['cases'] if c['id'] == slot['caseId'])
        result = verify(read(root / 'trials' / row['slot'] / 'result.json'))
        if row.get('actorType') not in ('human', 'agent') or not row.get('actor') or not row.get('provenance') or row.get('evidenceSha256') != digest(result):
            raise ValueError('Explicit actor, provenance and matching evidence hash required')
        if {r['id'] for r in row['requirements']} != {r['id'] for r in case['requirements']} or any(r['status'] not in ('PASS', 'FAIL', 'INCOMPLETE') or not r.get('evidence') for r in row['requirements']):
            raise ValueError('Review must cover each requirement with evidence')
        grades = sorted((root / 'grades').glob(row['slot'] + '-*.json'))
        if not grades or row.get('gradeSha256') != digest(read(grades[-1])):
            raise ValueError('Review must bind current grade hash')
        write(root / 'reviews' / (row['slot'] + '-' + stamp() + '.json'), row)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command', required=True)
    ls = commands.add_parser('list'); ls.add_argument('--suite')
    commands.add_parser('check')
    dg = commands.add_parser('diagnose'); dg.add_argument('--output', required=True); dg.add_argument('--ids', default='')
    pl = commands.add_parser('plan'); pl.add_argument('--suite', required=True); pl.add_argument('--config', required=True); pl.add_argument('--output', required=True)
    ru = commands.add_parser('run'); ru.add_argument('--plan', required=True); ru.add_argument('--metadata', required=True); ru.add_argument('--output', required=True); ru.add_argument('--materials', default='artifacts/agent-eval/materials'); ru.add_argument('--slots', default='', help='Explicit subset of frozen slots; started slots remain immutable')
    gr = commands.add_parser('grade'); gr.add_argument('--run', required=True); gr.add_argument('--mode', choices=('model', 'deterministic'), default='model'); gr.add_argument('--source-user', default='admin'); gr.add_argument('--slots', default='', help='Explicit comma-separated slots for a new offline grading version')
    rv = commands.add_parser('review'); rv.add_argument('--run', required=True); rv.add_argument('--decisions', required=True)
    rp = commands.add_parser('report'); rp.add_argument('--run', required=True)
    co = commands.add_parser('compare'); co.add_argument('--baseline', required=True); co.add_argument('--candidate', required=True)
    cl = commands.add_parser('cleanup'); cl.add_argument('--metadata', required=True); cl.add_argument('--runs', nargs='+', required=True); cl.add_argument('--apply', action='store_true')
    ca = commands.add_parser('calibrate'); ca.add_argument('--output', required=True); ca.add_argument('--source-user', default='admin'); ca.add_argument('--ids', default=''); ca.add_argument('--replay', help='Revalidate immutable typed-evidence calibration without new model calls')
    args = p.parse_args()
    if args.command == 'list':
        value = catalog()
        if args.suite:
            ids = read(BASE / 'suites.json')['suites'][args.suite]['cases']; value = [c for c in value['cases'] if c['id'] in ids]
        print(json.dumps(value, ensure_ascii=False, indent=2))
    elif args.command == 'diagnose':
        from .diagnostics import run as diagnose
        print(json.dumps(diagnose(args.output, set(args.ids.split(',')) if args.ids else None)))
    elif args.command == 'check':
        from .checks import check
        check()
    elif args.command == 'plan':
        value = plan(args.suite, read(args.config)); write(args.output, value); print(json.dumps({'slots': len(value['slots']), 'plan': args.output, 'providerCalls': 0}))
    elif args.command == 'run':
        asyncio.run(run(args))
    elif args.command == 'grade':
        asyncio.run(grade(args))
    elif args.command == 'review':
        review(args)
    elif args.command == 'report':
        from .report import report, render
        root = Path(args.run); value = report(root); target = root / ('report-' + stamp()); write(target.with_suffix('.json'), value); target.with_suffix('.html').write_text(render(value)); print(json.dumps({'status': value['status'], 'denominator': value['denominator'], 'report': str(target)}))
    elif args.command == 'calibrate':
        from .calibration import calibrate
        print(json.dumps(asyncio.run(calibrate(args)), ensure_ascii=False, indent=2))
    elif args.command == 'cleanup':
        from .cleanup import cleanup
        print(json.dumps(cleanup(args.metadata, args.runs, args.apply), ensure_ascii=False, indent=2))
    elif args.command == 'compare':
        from .report import compare
        print(json.dumps(compare(Path(args.baseline), Path(args.candidate)), ensure_ascii=False, indent=2))
    return 0
