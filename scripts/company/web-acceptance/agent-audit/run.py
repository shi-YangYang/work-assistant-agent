"""Frozen serial real-model campaign; no retries, production mutations or silent effort changes."""
import argparse
import asyncio
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parent))
from runner_environment import runner_environment
import httpx

spec = importlib.util.spec_from_file_location('legacy_http', BASE.parent / 'agent-http.py')
http = importlib.util.module_from_spec(spec)
spec.loader.exec_module(http)
import approval
approval.install(http)
latency_spec = importlib.util.spec_from_file_location('latency_observer', BASE.parents[2] / 'benchmarks/assistant-latency.py')
latency = importlib.util.module_from_spec(latency_spec)
latency_spec.loader.exec_module(latency)
settle_authorized = http.settle


async def observed_settle(client, receipt, timeout, **kwargs):
    case, directory = approval.current.get()
    turn = approval.accepted_turn(http, directory, receipt)
    metrics = {'firstSseTextSeconds': None, 'terminalSseSeconds': None, 'basis': 'accepted receipt to SSE observation; not browser paint'}
    observer = asyncio.create_task(latency.observe(client, receipt, time.perf_counter(), directory / f'sse-{turn}.jsonl', 2, metrics))
    try:
        return await settle_authorized(client, receipt, timeout, **kwargs)
    finally:
        if not observer.done():
            observer.cancel()
        outcome = await asyncio.gather(observer, return_exceptions=True)
        if isinstance(outcome[0], Exception) and not isinstance(outcome[0], asyncio.CancelledError):
            metrics['observerError'] = type(outcome[0]).__name__
        (directory / f'metrics-{turn}.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2))


http.settle = observed_settle


async def configure_case(case, state, directory):
    account = state['users'][case['role']]
    async with httpx.AsyncClient(base_url=state['apiOrigin'], headers={'Origin': state['origin']}, timeout=45) as client:
        identity = http.checked(await client.post('/api/v1/auth/login', json={'username': account['username'], 'password': account['password']}))
        client.headers['X-CSRF-Token'] = identity['csrf']
        memory = http.checked(await client.get('/api/v1/assistant/memory'))
        if not memory['enabled']:
            memory = http.checked(await client.patch('/api/v1/assistant/memory/settings', json={'enabled': True, 'expectedRevision': memory['revision']}))
        # Predeclared synthetic-memory fixture reset, not part of tool statistics.
        http.checked(await client.put('/api/v1/assistant/memory/document', json={'markdown': '', 'expectedRevision': memory['revision']}))
        reasoning = http.checked(await client.get('/api/v1/assistant/reasoning-settings'))
        if case['effort'] not in [v['effort'] for v in reasoning['options']]:
            raise RuntimeError('Frozen reasoning effort unavailable; refusing downgrade')
        if reasoning['selected']['effort'] != case['effort']:
            reasoning = http.checked(await client.patch('/api/v1/assistant/reasoning-settings', json={'effort': case['effort'], 'preferenceRevision': reasoning['preferenceRevision'], 'configVersion': reasoning['configVersion']}))
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'settings.json').write_text(json.dumps({'role': case['role'], 'reasoning': reasoning, 'mode': case['mode'], 'persona': case['persona'], 'fixtureReset': 'memory only'}, ensure_ascii=False, indent=2))
        await client.post('/api/v1/auth/logout', json={})


async def main(args):
    _, metadata, state = runner_environment(metadata_path=args.metadata)
    suite = json.loads((BASE / 'suite.json').read_text())
    cases_path = BASE / 'cases.json'
    sha = hashlib.sha256(cases_path.read_bytes()).hexdigest()
    if sha != suite['caseSha256']:
        raise RuntimeError('Frozen cases fingerprint mismatch')
    cases = json.loads(cases_path.read_text())
    if args.ids:
        cases = [c for c in cases if c['id'] in args.ids.split(',')]
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    run = {'caseSha256': sha, 'schema': metadata['schema'], 'runId': metadata['runId'], 'applicationCommit': metadata['commit'], 'ids': args.ids, 'repetition': args.repetition, 'timeoutSeconds': suite['watchdogSeconds'], 'concurrency': 1}
    previous = Path(args.continue_from).resolve() if args.continue_from else None
    if previous:
        if previous == output.resolve() or not args.resume_reason:
            raise RuntimeError('Continuation requires separate output and an explicit environment/harness interruption reason')
        original_run = json.loads((previous / 'run.json').read_text())
        for key in ('caseSha256', 'schema', 'runId', 'applicationCommit', 'repetition', 'timeoutSeconds', 'concurrency'):
            if original_run.get(key) != run[key]:
                raise RuntimeError('Continuation must retain the frozen cases, application and owned environment')
        run.update(continuedFrom=str(previous), reason=args.resume_reason)
    marker = output / 'run.json'
    if marker.exists():
        if not args.resume or json.loads(marker.read_text()) != run:
            raise RuntimeError('Existing run does not match')
    else:
        marker.write_text(json.dumps(run, indent=2))
    for original in cases:
        case = copy.deepcopy(original)
        if args.repetition > 1 and case['id'] not in suite['highRiskRepetition']['caseIds']:
            continue
        directory = output / case['id']
        if args.repetition > 1:
            import re
            titles = set(re.findall('“([^”]+)”', case['turns'][0])) if 'work' in str(case['mutationBounds']).lower() else set()
            for title in titles:
                if any(b['workCreate'] for b in case['mutationBounds']):
                    case['turns'] = [turn.replace(title, title + '-r' + str(args.repetition)) for turn in case['turns']]
        if (directory / 'result.json').exists() or (directory / 'first.jsonl').exists() or (directory / 'setup-failure.json').exists():
            if args.resume:
                continue
            raise RuntimeError('Refusing to overwrite initial observations')
        prior = previous / case['id'] if previous else None
        rows = http.read_rows(prior / 'first.jsonl') if prior else []
        if rows and (rows[-1].get('message', {}).get('job', {}).get('state') in ('failed', 'awaiting_retry') or len(rows) == len(case['turns']) and all(not row.get('exception') for row in rows)):
            continue
        try:
            directory.mkdir(parents=True, exist_ok=True)
            admitted = bool(prior and (prior / 'accepted.jsonl').exists())
            if not admitted:
                await configure_case(case, state, directory)
            else:
                # Never clear memory or replace the user's settings after a
                # message was accepted. The legacy driver recovers its receipt.
                (directory / 'recovery-accepted.jsonl').write_bytes((prior / 'accepted.jsonl').read_bytes())
                if (prior / 'settings.json').exists():
                    (directory / 'settings.json').write_bytes((prior / 'settings.json').read_bytes())
            token = approval.current.set((case, directory))
            try:
                await http.execute_case(case, state, output, Path(args.materials), suite['watchdogSeconds'], previous=prior if admitted else None)
            finally:
                approval.current.reset(token)
        except Exception as error:
            directory.mkdir(parents=True, exist_ok=True)
            (directory / 'setup-failure.json').write_text(json.dumps({'case': case['id'], 'type': type(error).__name__, 'detail': str(error)[:500], 'time': time.time()}, ensure_ascii=False, indent=2))
            print(json.dumps({'case': case['id'], 'setupFailure': type(error).__name__}), flush=True)
    print(json.dumps({'completedRun': str(output), 'repetition': args.repetition}), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--metadata', required=True)
    p.add_argument('--materials', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--ids', default='')
    p.add_argument('--repetition', type=int, choices=[1, 2, 3], default=1)
    p.add_argument('--resume', action='store_true')
    p.add_argument('--continue-from', help='Recover unfinished receipts from an immutable prior campaign into a new directory')
    p.add_argument('--resume-reason', default='', help='Required explanation of the environment/harness interruption; not a product retry')
    asyncio.run(main(p.parse_args()))
