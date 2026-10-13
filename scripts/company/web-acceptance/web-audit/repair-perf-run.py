"""One frozen, serial AB/BA campaign; preserve every first result without resampling."""
import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import time
from uuid import uuid4

import httpx
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[4]
BASE = ROOT / 'scripts/company/web-acceptance'
OWNED_ROOT = ROOT / 'artifacts/spec068/repair-performance'
output_parser = argparse.ArgumentParser(add_help=False)
output_parser.add_argument('--output', type=Path, default=OWNED_ROOT)
output_args, _ = output_parser.parse_known_args()
OUT = output_args.output.resolve()
if OUT not in (OWNED_ROOT, OWNED_ROOT/'v2'):
    raise RuntimeError('Only exact owned performance output directories are allowed')
sys.path.insert(0, str(BASE))
from environment import load_environment

spec = importlib.util.spec_from_file_location('repair_latency', ROOT / 'scripts/benchmarks/assistant-latency.py')
latency = importlib.util.module_from_spec(spec)
spec.loader.exec_module(latency)
TERMINAL = latency.TERMINAL


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def readback(private, owner):
    engine = create_engine(private['environment']['DATABASE_URL'])
    tables = ['company_work_item', 'company_work_revision', 'company_report', 'company_report_revision',
              'company_image_generation', 'company_deliverable', 'company_deliverable_revision',
              'company_business_action', 'company_model_usage', 'company_job']
    result = {}
    try:
        with engine.connect() as db:
            db.execute(text('SET TRANSACTION READ ONLY'))
            for table in tables:
                result[table] = [row[0] for row in db.execute(text(f'SELECT row_to_json(t) FROM {table} t WHERE owner_id=:owner'), {'owner': owner})]
    finally:
        engine.dispose()
    return result


def selected_trace(path, owner):
    return [row for row in rows(path) if row.get('ownerId') == owner]


def counts(trace, snapshot):
    kinds = lambda key: [r for r in trace if r['kind'] == key]
    main = kinds('model_attempt_start')
    provider = kinds('provider_request_start')
    job_kinds = {r['id']: r['kind'] for r in snapshot['company_job']}
    sends = [{**r['timing'], 'jobKind': job_kinds.get(r.get('jobId'), 'unknown')} for r in kinds('repair_timing') if (r.get('timing') or {}).get('event') == 'model.send']
    labels = [r['jobKind'] + '/' + r.get('kind', 'unknown') for r in sends]
    by_kind = {kind: labels.count(kind) for kind in sorted(set(labels))}
    main_count = sum(count for kind, count in by_kind.items() if kind in ('message/main', 'message/protocol', 'message/completion_repair', 'message/response_repair'))
    return {'modelAttempts': len(main), 'totalProviderRequests': len(provider), 'modelRequestsByKind': by_kind,
            'mainModelRequests': main_count, 'auxiliaryProviderRequests': len(provider)-main_count,
            'auxiliaryParameters': [r.get('config') for r in provider],
            'mainParameters': [r.get('adapterParameters') for r in main],
            'toolRequests': len(kinds('tool_dispatch')),
            'toolRequestsByName': {name: sum(r.get('tool') == name for r in kinds('tool_dispatch'))
                for name in sorted({r.get('tool', '') for r in kinds('tool_dispatch')})},
            'toolHandlerExecutions': len(kinds('tool_attempt_start')),
            'controlledImageProviderCalls': len(kinds('controlled_image_provider')),
            'reportRows': len(snapshot['company_report']),
            'reportRevisions': len(snapshot['company_report_revision']),
            'imageRows': len(snapshot['company_image_generation']),
            'successfulImages': sum(r['state'] == 'succeeded' for r in snapshot['company_image_generation']),
            'deliverables': len(snapshot['company_deliverable']),
            'deliverableRevisions': len(snapshot['company_deliverable_revision']),
            'businessActions': len(snapshot['company_business_action']),
            'usage': [{k: r.get(k) for k in ('kind', 'status', 'actual_input_tokens', 'actual_output_tokens', 'elapsed_ms')} for r in snapshot['company_model_usage']]}


def invariants(case, result, before, after):
    message = result.get('message', {})
    report = after['company_report']
    deliverables = after['company_deliverable_revision']
    files = [file for row in deliverables for file in row.get('files', [])]
    states = {'answerCompleted': message.get('job', {}).get('state') in ('succeeded', 'awaiting_input') and not message.get('interactions') and (message.get('job', {}).get('taskOutcome') or {}).get('state') == 'completed',
              'nonemptyReply': bool(message.get('reply', '').strip()),
              'workUnchanged': before['company_work_item'] == after['company_work_item'] and before['company_work_revision'] == after['company_work_revision'],
              'noReportSubmission': all(not r['published_revision'] for r in report),
              'noForeignOwnership': all(r.get('owner_id') == result['actorId'] for table in after.values() for r in table)}
    if case['id'] == 'ordinary':
        states.update(noReports=not report, noImages=not after['company_image_generation'], noDeliverables=not deliverables)
    if case['id'] == 'report':
        states.update(oneDraft=len(report) == 1 and report[0]['kind'] == 'weekly' and report[0]['revision'] >= 1 and any(report[0]['content'].values()),
                      noImages=not after['company_image_generation'],
                      noRemainingOutcome=not (message.get('job', {}).get('taskOutcome') or {}).get('remaining'))
    if case['id'] == 'images':
        states.update(noReports=not report,
                      fourSuccessfulImages=result['counts']['successfulImages'] == 4,
                      fourActualImageCalls=result['counts']['controlledImageProviderCalls'] == 4,
                      fourFiles=len(files) == 4,
                      oneMessageDelivery=bool(deliverables) and all(r['message_id'] == result.get('receipt', {}).get('messageId') for r in deliverables),
                      noRemainingOutcome=not (message.get('job', {}).get('taskOutcome') or {}).get('remaining'))
    return states


async def execute(version, case, metadata, private):
    directory = OUT / 'observations' / (case['alias'] + '-' + version)
    continuing = (directory/'admission.json').exists()
    if directory.exists() and not continuing:
        raise RuntimeError('Existing unaccepted observation needs explicit inspection')
    directory.mkdir(parents=True, exist_ok=True)
    actor = private['accounts'][case['alias']]
    before = json.loads((directory/'before.json').read_text()) if continuing else readback(private, actor['id'])
    if not continuing:
        write(directory/'before.json', before)
    result = {'case': case['id'], 'alias': case['alias'], 'version': version, 'effort': case['effort'],
              'repetition': case['repetition'], 'actorId': actor['id'], 'prompt': case['prompt'],
              'metrics': {'firstSseTextSeconds': None, 'terminalSseSeconds': None, 'finalReadbackSeconds': None},
              'startedAt': time.time(), 'browserFirstPaintSeconds': None}
    if continuing:
        if (directory/'result.json').exists():
            (directory/'initial-result.json').write_bytes((directory/'result.json').read_bytes())
            result = json.loads((directory/'result.json').read_text())
        admission = json.loads((directory/'admission.json').read_text())
        result['startedAt'] = admission['sendUnixTime']
        result['receipt'] = admission['receipt']
        result['continuedWithoutResending'] = True
        result['observerCorrection'] = 'Wait child report completion; preserve initial observation and use correlated worker completion event for comparable duration'
    async with httpx.AsyncClient(base_url=metadata['apiOrigin'], headers={'Origin': metadata['origin']}, timeout=45, trust_env=False) as client:
        identity = latency.checked(await client.post('/api/v1/auth/login', json={'username': actor['username'], 'password': actor['password']}))
        client.headers['X-CSRF-Token'] = identity['csrf']
        reasoning = latency.checked(await client.get('/api/v1/assistant/reasoning-settings'))
        if case['effort'] not in [item['effort'] for item in reasoning['options']]:
            raise RuntimeError('Frozen effort unavailable; refusing fallback')
        if reasoning['selected']['effort'] != case['effort']:
            reasoning = latency.checked(await client.patch('/api/v1/assistant/reasoning-settings', json={'effort': case['effort'], 'preferenceRevision': reasoning['preferenceRevision'], 'configVersion': reasoning['configVersion']}))
        memory = latency.checked(await client.get('/api/v1/assistant/memory'))
        execution = latency.checked(await client.get('/api/v1/assistant/execution-settings'))
        if execution['executionMode'] != case['executionMode']:
            raise RuntimeError('Frozen execution mode mismatch')
        result['settings'] = {'reasoning': reasoning, 'execution': execution, 'memory': memory}
        write(directory/'settings.json', result['settings'])
        body = {'text': case['prompt'], 'newConversation': True, 'personaId': case['persona'], 'attachmentIds': [],
                'reasoning': {'effort': case['effort'], 'preferenceRevision': reasoning['preferenceRevision'], 'configVersion': reasoning['configVersion']}}
        began = time.perf_counter() - (time.time()-result['startedAt']) if continuing else time.perf_counter()
        observer = None
        receipt = None
        try:
            if continuing:
                receipt = result['receipt']
            else:
                result['startedAt'] = time.time()
                receipt = latency.checked(await client.post('/api/v1/messages', json=body, headers={'Idempotency-Key': str(uuid4())}), (202,))
                result['receipt'] = receipt
                result['metrics']['admittedSeconds'] = time.perf_counter()-began
                write(directory/'admission.json', {'receipt': receipt, 'sendUnixTime': result['startedAt']})
            observer = asyncio.create_task(latency.observe(client, receipt, began, directory/('sse-continuation.jsonl' if continuing else 'sse.jsonl'), 2, result['metrics']))
            async with asyncio.timeout(1200):
                while True:
                    message = latency.checked(await client.get('/api/v1/messages/' + receipt['messageId']))
                    cards = message.get('actions', [])
                    busy = any(card.get('state') == 'running' or (card.get('job') or {}).get('state') in ('queued', 'running') for card in cards)
                    if message.get('job', {}).get('state') in TERMINAL and not busy:
                        result['message'] = message
                        result['metrics']['finalReadbackSeconds'] = time.perf_counter()-began
                        break
                    await asyncio.sleep(.25)
            if observer:
                try:
                    await asyncio.wait_for(asyncio.shield(observer), timeout=1)
                except TimeoutError:
                    observer.cancel()
            (directory/'answer.txt').write_text(result['message'].get('reply', ''))
        except Exception as error:
            result['exception'] = {'type': type(error).__name__, 'detail': str(error)[:500]}
            if receipt:
                job = latency.checked(await client.get('/api/v1/jobs/' + receipt['jobId']))
                if job['state'] in ('queued', 'running'):
                    cancelled = await client.post('/api/v1/jobs/' + receipt['jobId'] + '/cancel', json={'expectedAttempt': job['attempt'], 'expectedFence': job['fence']})
                    result['cleanupCancelStatus'] = cancelled.status_code
        finally:
            if observer:
                observer.cancel()
                outcome = await asyncio.gather(observer, return_exceptions=True)
                if isinstance(outcome[0], Exception):
                    result['observerError'] = type(outcome[0]).__name__
        result['wallSeconds'] = time.perf_counter()-began
        await client.post('/api/v1/auth/logout', json={})
    after = readback(private, actor['id'])
    trace = selected_trace(OUT/f'{version}-trace.jsonl', actor['id'])
    write(directory/'after.json', after)
    write(directory/'trace.json', trace)
    result['counts'] = counts(trace, after)
    completed_events = [r['time'] for r in trace if r['kind'] == 'worker_job_end']
    result['metrics']['taskWorkerEndSeconds'] = max(completed_events)-result['startedAt'] if completed_events else None
    result['metrics']['taskWorkerEndDefinition'] = 'Latest correlated message/report worker end after persistent result; not browser paint'
    result['invariants'] = invariants(case, result, before, after)
    result['semanticReview'] = 'pending offline review of preserved answers/report contents/requests'
    if result['metrics']['firstSseTextSeconds'] is None:
        result['metrics']['firstSseTextUnavailableReason'] = 'No authorized nonempty SSE reply body observed; not zero'
    write(directory/'result.json', result)
    latency.append(OUT/'observations.jsonl', result)
    print(json.dumps({'case': case['alias'], 'version': version, 'seconds': result['metrics']['finalReadbackSeconds'],
                      'firstBody': result['metrics']['firstSseTextSeconds'], 'counts': {k: result['counts'][k] for k in ('mainModelRequests', 'auxiliaryProviderRequests', 'toolRequests', 'controlledImageProviderCalls')},
                      'failedInvariants': [k for k, v in result['invariants'].items() if not v], 'error': result.get('exception')}, ensure_ascii=False), flush=True)


async def main():
    resources = json.loads((OUT/'resources.json').read_text())
    case_path = OUT/('cases-explicit-report.json' if '--explicit-report' in sys.argv else 'cases.json')
    cases = json.loads(case_path.read_text())
    continuation = '--continue-observed' in sys.argv
    if (OUT/'run.json').exists() and not continuation:
        raise RuntimeError('An experiment already exists; do not resample')
    manifests = {}
    for version in ('baseline', 'candidate'):
        source = OUT/version
        hashes = json.loads((OUT/(version+'-hashes.json')).read_text())
        for filename, expected in hashes.items():
            if hashlib.sha256((source/filename).read_bytes()).hexdigest() != expected:
                raise RuntimeError('Frozen source changed')
        manifests[version] = load_environment(resources['manifests'][version])
    run = {'frozenCasesSha256': hashlib.sha256(case_path.read_bytes()).hexdigest(),
           'versions': {version: hashlib.sha256((OUT/(version+'-hashes.json')).read_bytes()).hexdigest() for version in manifests},
           'concurrency': 1, 'startedAt': time.time(), 'observationCount': cases['observations'], 'processes': []}
    old_run = json.loads((OUT/'run.json').read_text()) if continuation else None
    if continuation:
        if old_run['versions'] != run['versions']:
            raise RuntimeError('Continuation source mismatch')
        accepted_sha = run['frozenCasesSha256']
        if old_run['frozenCasesSha256'] != accepted_sha and '--explicit-report' not in sys.argv:
            raise RuntimeError('Continuation input mismatch')
        run = old_run
        if '--explicit-report' in sys.argv:
            run['explicitReportCasesSha256'] = accepted_sha
            run['observationCount'] = 28
            run['comparableObservationCount'] = 24
            run['originalReportDiagnosticCount'] = 4
        run['continuationReason'] = 'Await child report completion; no resends; preserve original observations'
    write(OUT/'run.json', run)
    processes = []
    try:
        for version, (metadata, _) in manifests.items():
            for service in (() if continuation else ('api', 'worker')):
                log = (OUT/f'{version}-{service}.log').open('w')
                env = {k: v for k, v in os.environ.items() if k.lower() not in ('http_proxy', 'https_proxy', 'all_proxy')}
                process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('repair-perf-runtime.py')),
                    '--metadata', resources['manifests'][version], '--source', str(OUT/version), '--trace', str(OUT/f'{version}-trace.jsonl'), service],
                    cwd=ROOT, env={**env, 'PYTHONDONTWRITEBYTECODE': '1'}, stdout=log, stderr=subprocess.STDOUT)
                processes.append((process, log))
                run['processes'].append({'pid': process.pid, 'version': version, 'service': service})
                write(OUT/'run.json', run)
            async with httpx.AsyncClient(timeout=2, trust_env=False) as health:
                for _ in range(150):
                    if any(p.poll() is not None for p, _ in processes):
                        raise RuntimeError('Owned runtime startup failed')
                    try:
                        if (await health.get(metadata['apiOrigin']+'/api/v1/health')).status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    await asyncio.sleep(.1)
                else:
                    raise RuntimeError('Owned API health deadline')
        for case in cases['pairs']:
            for version in case['order']:
                directory = OUT/'observations'/(case['alias']+'-'+version)
                if continuation and (directory/'result.json').exists():
                    prior = json.loads((directory/'result.json').read_text())
                    if case['id'] != 'report' or not any(card.get('state') == 'running' or (card.get('job') or {}).get('state') in ('queued', 'running') for card in prior.get('message', {}).get('actions', [])):
                        continue
                await execute(version, case, *manifests[version])
    finally:
        for process, _ in processes:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
        for process, log in processes:
            try:
                await asyncio.to_thread(process.wait, 15)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, 5)
            log.close()
        if continuation:
            stopped = []
            for row in run['processes']:
                try:
                    actual = subprocess.check_output(['ps', '-p', str(row['pid']), '-o', 'command='], text=True)
                    if 'repair-perf-runtime.py' not in actual or str(OUT/row['version']) not in actual:
                        raise RuntimeError('PID no longer belongs to repair runtime')
                    os.kill(row['pid'], signal.SIGTERM)
                    stopped.append({**row, 'signalSent': 'SIGTERM'})
                except subprocess.CalledProcessError:
                    stopped.append({**row, 'alreadyStopped': True})
            write(OUT/'process-cleanup.json', {'ownedProcesses': stopped})
        else:
            write(OUT/'process-cleanup.json', {'ownedProcesses': [{**row, 'exitCode': processes[i][0].returncode} for i, row in enumerate(run['processes'])]})
        run['endedAt'] = time.time()
        write(OUT/'run.json', run)


if __name__ == '__main__':
    asyncio.run(main())
