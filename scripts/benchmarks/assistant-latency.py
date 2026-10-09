"""Frozen real-model turns through an explicitly owned acceptance API.

Each invocation refuses existing admissions/results and never retries a request.
Timing is HTTP send to SSE body observation, not browser paint. Use the same
cases file and frozen model/effort for baseline and after; preserve failures.

Example:
 .venv-server/bin/python scripts/benchmarks/assistant-latency.py \
   --metadata artifacts/spec055/20261008-latency/baseline/environment.json \
   --cases artifacts/spec055/20261008-latency/cases.json --protocol 1
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from uuid import uuid4
import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/company/web-acceptance'))
from environment import load_environment

TERMINAL = {'succeeded', 'failed', 'cancelled', 'awaiting_retry', 'awaiting_input'}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def append(path, value):
    with path.open('a') as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + '\n')
        stream.flush()


def checked(response, statuses=(200,)):
    if response.status_code not in statuses:
        raise RuntimeError(f'HTTP {response.status_code}: {response.text[:350]}')
    return response.json()


async def works(client):
    rows, cursor = [], None
    while True:
        data = checked(await client.get('/api/v1/work-items', params={'limit': 20, **({'cursor': cursor} if cursor else {})}))
        rows.extend(data['items'])
        cursor = data.get('nextCursor')
        if not cursor:
            return rows


async def observe(client, receipt, began, path, protocol, metrics):
    event, data = '', []
    url = f"/api/v1/jobs/{receipt['jobId']}/events"
    async with client.stream('GET', url, params={'version': protocol}, timeout=None) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line.startswith('event:'):
                event = line[6:].strip()
            elif line.startswith('data:'):
                data.append(line[5:].strip())
            elif not line and data:
                value = json.loads('\n'.join(data))
                elapsed = time.perf_counter() - began
                append(path, {'seconds': elapsed, 'event': event, 'body': value})
                text = ''
                if event == 'snapshot':
                    text = (value.get('replyStream') or {}).get('text') or ''
                    if value.get('state') in TERMINAL and metrics['terminalSseSeconds'] is None:
                        metrics['terminalSseSeconds'] = elapsed
                elif event == 'reply_sync':
                    text = value.get('text') or ''
                elif event == 'reply_delta':
                    text = value.get('delta') or ''
                if text.strip() and metrics['firstSseTextSeconds'] is None:
                    metrics['firstSseTextSeconds'] = elapsed
                event, data = '', []


async def execute(args):
    metadata, private = load_environment(args.metadata)
    if metadata.get('suite') not in ('spec055', 'spec056'):
        raise RuntimeError('This benchmark requires its explicitly owned performance environment')
    cases_path = Path(args.cases).resolve()
    manifest = json.loads(cases_path.read_text())
    if 'journeys' in manifest:
        choices = [item for item in manifest['journeys'] if item['id'] == args.journey]
        if len(choices) != 1 or args.effort not in choices[0]['efforts']:
            raise RuntimeError('Select a frozen journey and one of its configured efforts')
        manifest = {**manifest, **choices[0], 'effort': args.effort}
        if manifest.get('fixture') or manifest.get('workReference'):
            raise RuntimeError('Fixture journeys require assistant-latency-browser.mjs and a prepared owned environment')
    if not manifest.get('turns') or len({item['id'] for item in manifest['turns']}) != len(manifest['turns']):
        raise RuntimeError('Frozen turns require unique IDs and at least one input')
    if args.only_case and not (args.output and args.correction_reason):
        raise RuntimeError('A correction requires a separate output directory and an explicit reason')
    output = Path(args.output).resolve() if args.output else Path(args.metadata).resolve().parent
    output.mkdir(parents=True, exist_ok=True)
    selected = [(index, case) for index, case in enumerate(manifest['turns']) if not args.only_case or case['id'] == args.only_case]
    if not selected or args.only_case and (len(selected) != 1 or selected[0][1].get('continuePrevious')):
        raise RuntimeError('A correction must select exactly one independent frozen case')
    if (output / 'admissions.jsonl').exists() or (output / 'results.jsonl').exists():
        raise RuntimeError('Refusing to resend or overwrite immutable first results')
    actor = private['accounts'][args.actor]
    session = {'suite': metadata['suite'], 'runId': metadata['runId'], 'schema': metadata['schema'], 'casesSha256': hashlib.sha256(cases_path.read_bytes()).hexdigest(), 'protocol': args.protocol, 'sourceCommit': metadata['commit'], 'timingDefinition': 'send start to first nonempty SSE reply body; not browser paint', 'browserFirstPaintSeconds': None, 'browserFirstPaintUnavailableReason': 'HTTP/SSE benchmark; browser observation is separate evidence', 'modelCallDurationCaveat': 'includes HTTP and callbacks, not pure provider computation', 'correctionCase': args.only_case, 'correctionReason': args.correction_reason, 'actor': args.actor}
    async with httpx.AsyncClient(base_url=metadata['apiUrl'], headers={'Origin': metadata['origin']}, timeout=45) as client:
        identity = checked(await client.post('/api/v1/auth/login', json={'username': actor['username'], 'password': actor['password']}))
        client.headers['X-CSRF-Token'] = identity['csrf']
        execution = checked(await client.get('/api/v1/assistant/execution-settings'))
        if execution['executionMode'] != 'full':
            execution = checked(await client.patch('/api/v1/assistant/execution-settings', json={'executionMode': 'full', 'fullAccessConfirmed': True, 'expectedRevision': execution['modeRevision']}))
        reasoning = checked(await client.get('/api/v1/assistant/reasoning-settings'))
        if reasoning.get('selected', {}).get('effort') != manifest['effort']:
            raise RuntimeError('Effective model effort differs from frozen manifest')
        session.update({'reasoning': reasoning, 'execution': execution, 'beforeWorks': await works(client)})
        write_json(output / 'session.json', session)
        conversation = None
        for index, case in selected:
            directory = output / f"{index + 1:02d}-{case['id']}"
            directory.mkdir()
            body = {'text': case['prompt'], 'attachmentIds': [], 'reasoning': {'effort': reasoning['selected']['effort'], 'preferenceRevision': reasoning['preferenceRevision'], 'configVersion': reasoning['configVersion']}}
            if case.get('continuePrevious'):
                body['conversationId'] = conversation
            else:
                body.update({'newConversation': True, 'personaId': 'professional'})
            row = {'case': case['id'], 'turn': index + 1, 'prompt': case['prompt'], 'protocol': args.protocol, 'metrics': {'firstSseTextSeconds': None, 'terminalSseSeconds': None, 'finalReadbackSeconds': None}, 'beforeWorks': await works(client)}
            began = time.perf_counter()
            observer = None
            receipt = None
            try:
                receipt = checked(await client.post('/api/v1/messages', json=body, headers={'Idempotency-Key': str(uuid4())}), (202,))
                row['receipt'] = receipt
                row['metrics']['admittedSeconds'] = time.perf_counter() - began
                append(output / 'admissions.jsonl', {'case': case['id'], 'receipt': receipt, 'sentAt': time.time()})
                conversation = receipt['conversationId']
                observer = asyncio.create_task(observe(client, receipt, began, directory / 'sse.jsonl', args.protocol, row['metrics']))
                async with asyncio.timeout(args.timeout):
                    while True:
                        message = checked(await client.get('/api/v1/messages/' + receipt['messageId']))
                        if message.get('job', {}).get('state') in TERMINAL:
                            row['message'] = message
                            row['metrics']['finalReadbackSeconds'] = time.perf_counter() - began
                            break
                        await asyncio.sleep(.5)
                try:
                    await asyncio.wait_for(asyncio.shield(observer), timeout=3)
                except TimeoutError:
                    observer.cancel()
                answer = row['message'].get('reply', '')
                row['actualLength'] = {'unicodeCharacters': len(answer), 'nonWhitespaceCharacters': len(re.sub(r'\s', '', answer)), 'hanCharacters': len(re.findall(r'[\u3400-\u9fff]', answer))}
                (directory / 'answer.txt').write_text(answer)
            except Exception as error:
                row['exception'] = {'type': type(error).__name__, 'message': str(error)[:500]}
                if receipt:
                    job = checked(await client.get('/api/v1/jobs/' + receipt['jobId']))
                    if job['state'] in ('queued', 'running'):
                        response = await client.post('/api/v1/jobs/' + receipt['jobId'] + '/cancel', json={'expectedAttempt': job['attempt'], 'expectedFence': job['fence']})
                        row['cleanupCancelStatus'] = response.status_code
            finally:
                if observer and not observer.done():
                    observer.cancel()
                if observer:
                    results = await asyncio.gather(observer, return_exceptions=True)
                    if isinstance(results[0], Exception):
                        row['observerError'] = type(results[0]).__name__
            if row['metrics']['firstSseTextSeconds'] is None:
                row['metrics']['firstSseTextUnavailableReason'] = 'No nonempty authorized reply body observed before stream ended'
            row['afterWorks'] = await works(client)
            row['wallSeconds'] = time.perf_counter() - began
            write_json(directory / 'result.json', row)
            append(output / 'results.jsonl', row)
            print(json.dumps({'case': case['id'], 'state': row.get('message', {}).get('job', {}).get('state'), 'metrics': row['metrics'], 'length': row.get('actualLength'), 'exception': row.get('exception')}, ensure_ascii=False), flush=True)
        session['afterWorks'] = await works(client)
        write_json(output / 'session.json', session)
        await client.post('/api/v1/auth/logout', json={})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', required=True)
    parser.add_argument('--cases', required=True)
    parser.add_argument('--journey', help='Journey from a multi-capability manifest')
    parser.add_argument('--effort', help='Frozen low/max stratum; never changes the daily account')
    parser.add_argument('--protocol', type=int, choices=(1, 2), required=True)
    parser.add_argument('--timeout', type=int, default=1200)
    parser.add_argument('--output', help='Separate immutable correction evidence directory')
    parser.add_argument('--only-case', help='One explicitly authorized environment correction, never a quality rerun')
    parser.add_argument('--actor', default='realEmployee')
    parser.add_argument('--correction-reason')
    asyncio.run(execute(parser.parse_args()))


if __name__ == '__main__':
    main()
