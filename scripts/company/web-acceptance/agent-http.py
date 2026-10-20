"""Opt-in real-model journeys through an owned API/worker; first results are immutable.

The manifest establishes DB ownership before any writes. Cases and expectations
are frozen outside this runner; a succeeded job still requires semantic review.
"""
import argparse
import asyncio
import hashlib
import json
import mimetypes
from pathlib import Path
from uuid import uuid4

import httpx
from runner_environment import runner_environment

TERMINAL = {'succeeded', 'failed', 'cancelled', 'awaiting_retry', 'awaiting_input'}


def checked(response, statuses=(200,)):
    if response.status_code not in statuses:
        raise RuntimeError(f'HTTP {response.status_code}: {response.text[:350]}')
    return response.json()


async def pages(client, path, **params):
    items, cursor, seen = [], None, set()
    while True:
        response = await client.get(path, params={**params, 'limit': 20, **({'cursor': cursor} if cursor else {})})
        if response.status_code != 200:
            return {'status': response.status_code}
        data = response.json()
        items.extend(data.get('items', []))
        cursor = data.get('nextCursor')
        if not cursor:
            return {'status': 200, 'items': items}
        if cursor in seen:
            raise RuntimeError('Pagination cursor repeated')
        seen.add(cursor)


async def read_pages(client, path, **params):
    """Legacy readback shape used by the existing focused retest entrypoint."""
    result = await pages(client, path, **params)
    return {'status': result['status'], 'body': {'items': result.get('items', []), 'nextCursor': None}}


async def snapshot(client):
    result = {}
    for label, path, params in (
        ('work', '/api/v1/work-items', {}),
        ('daily', '/api/v1/reports', {'kind': 'daily'}),
        ('weekly', '/api/v1/reports', {'kind': 'weekly'}),
    ):
        result[label] = await pages(client, path, **params)
    memory = await client.get('/api/v1/assistant/memory')
    result['memory'] = memory.json() if memory.status_code == 200 else {'status': memory.status_code}
    return result


async def settle(client, receipt, timeout, *, approve=False, progress=None):
    approvals = []
    receipts = {receipt['messageId']: receipt}

    def follow(reference):
        if not reference:
            return False
        if reference.get('conversationId') != receipt['conversationId']:
            raise RuntimeError('Continuation left the accepted conversation')
        if not reference.get('messageId') or not reference.get('jobId'):
            raise RuntimeError('Invalid continuation receipt')
        if reference['messageId'] in receipts:
            return False
        receipts[reference['messageId']] = reference
        if progress:
            progress({'kind': 'continuation', 'receipt': reference})
        return True

    async with asyncio.timeout(timeout):
        while True:
            values = [checked(await client.get('/api/v1/messages/' + identifier)) for identifier in list(receipts)]
            cards = {card['id']: card for value in values for card in value.get('actions', [])}
            discovered = False
            for card in cards.values():
                discovered = follow(card.get('continuation')) or discovered
            if discovered:
                continue
            busy = any(value.get('job', {}).get('state') not in TERMINAL for value in values)
            busy = busy or any(card['state'] == 'running' or (card.get('job') or {}).get('state') in ('queued', 'running') for card in cards.values())
            if not busy:
                # Only cards attached to this accepted message/continuation chain
                # are eligible, never unrelated pending cards in the conversation.
                pending = next((card for card in cards.values() if card['state'] == 'pending' and card.get('canConfirm') is True), None)
                if approve and pending:
                    result = checked(await client.post('/api/v1/business-actions/' + pending['id'] + '/confirm', json={'expectedRevision': pending['revision']}))
                    approval = {'id': pending['id'], 'result': result}
                    approvals.append(approval)
                    if progress:
                        progress({'kind': 'approval', **approval})
                    follow(result.get('continuation'))
                    # Refresh before another choice: revisions and continuations
                    # may have changed as a consequence of this confirmation.
                    continue
                return values[-1], approvals
            # Harness observation only, not application reconnection behaviour.
            await asyncio.sleep(1)


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line] if path.exists() else []


def append_row(path, row):
    with path.open('a') as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        stream.flush()


async def recover_receipt(client, case, index, conversation, previous, prior_rows):
    """Recover admission without inspecting or changing frozen prompt semantics."""
    prior = next((row for row in prior_rows if row['turn'] == index + 1), None)
    if prior and prior.get('receipt'):
        return prior['receipt']
    accepted = [row for row in read_rows(previous / 'accepted.jsonl') if row['turn'] == index + 1]
    if accepted:
        return accepted[-1]['receipt']
    if not conversation:
        return None
    result = await pages(client, '/api/v1/messages', conversationId=conversation)
    if result['status'] != 200:
        raise RuntimeError('Cannot recover conversation admissions')
    known = {row['receipt']['messageId'] for row in prior_rows if row.get('receipt')}
    candidates = [message for message in result['items'] if message['id'] not in known and not message.get('replyTo')]
    if not candidates:
        return None
    if len(candidates) != 1 or candidates[0]['text'] != case['turns'][index]:
        raise RuntimeError('Ambiguous unrecorded admission; refusing to resend')
    message = candidates[0]
    return {'messageId': message['id'], 'jobId': message['job']['id'], 'conversationId': conversation}


async def files(client, value, directory):
    result = []
    for deliverable in value.get('deliverables', []):
        for item in deliverable.get('files', []):
            url = item['url']
            if not url.startswith('/api/v1/') or url.startswith('//'):
                raise RuntimeError('Unexpected generated download URL')
            response = await client.get(url)
            response.raise_for_status()
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / (str(len(result)) + '-' + Path(item['name']).name)
            target.write_bytes(response.content)
            result.append({'name': item['name'], 'size': len(response.content), 'declaredSize': item['size'], 'path': str(target), 'sha256': hashlib.sha256(response.content).hexdigest()})
    return result


async def execute_case(case, state, output, materials, timeout, *, previous=None):
    actor = state['users'][case['role']]
    directory = output / case['id']
    directory.mkdir(parents=True, exist_ok=True)
    first = directory / 'first.jsonl'
    if first.exists():
        raise RuntimeError('Refusing to overwrite first result: ' + case['id'])
    prior_rows = read_rows(previous / 'first.jsonl') if previous else []
    prior_success = {row['turn']: row for row in prior_rows if not row.get('exception') and row.get('message')}
    prior_before = previous / 'before.json' if previous else None
    loop = asyncio.get_running_loop()
    async with httpx.AsyncClient(base_url=state['apiOrigin'], headers={'Origin': state['origin']}, timeout=45) as client:
        identity = checked(await client.post('/api/v1/auth/login', json={'username': actor['username'], 'password': actor['password']}))
        client.headers['X-CSRF-Token'] = identity['csrf']
        if prior_success:
            boundary = prior_success[max(prior_success)]
            value, approvals = await settle(client, boundary['receipt'], timeout, approve=case.get('approveActions', False))
            (directory / 'recovered-boundary.json').write_text(json.dumps({'receipt': boundary['receipt'], 'message': value, 'approvals': approvals}, ensure_ascii=False, indent=2))
            if value.get('job', {}).get('state') in ('failed', 'awaiting_retry'):
                raise RuntimeError('Prior continuation needs explicit retry; refusing new turns')
        mode = checked(await client.get('/api/v1/assistant/execution-settings'))
        if mode['executionMode'] != case['mode']:
            checked(await client.patch('/api/v1/assistant/execution-settings', json={'executionMode': case['mode'], 'fullAccessConfirmed': True, 'expectedRevision': mode['modeRevision']}))
        if not (prior_before and prior_before.exists()):
            for seed in case.get('workFixtures', []):
                checked(await client.post('/api/v1/work-items', json=seed, headers={'Idempotency-Key': str(uuid4())}), (201,))
        before = json.loads(prior_before.read_text()) if prior_before and prior_before.exists() else await snapshot(client)
        (directory / 'before.json').write_text(json.dumps(before, ensure_ascii=False, indent=2))
        conversation, rows = None, []
        for index, prompt in enumerate(case['turns']):
            if index + 1 in prior_success:
                row = {**prior_success[index + 1], 'evidenceSource': str(previous / 'first.jsonl')}
                rows.append(row)
                conversation = row['receipt']['conversationId']
                continue
            if index in case.get('newConversationTurns', []):
                conversation = None
            receipt = await recover_receipt(client, case, index, conversation, previous, rows + [row for row in prior_rows if row.get('exception')]) if previous else None
            edit = case.get('memoryBeforeTurns', {}).get(str(index))
            prior_attempted = any(row['turn'] == index + 1 for row in prior_rows)
            if edit and not receipt and not prior_attempted:
                memory = checked(await client.get('/api/v1/assistant/memory'))
                if 'enabled' in edit:
                    memory = checked(await client.patch('/api/v1/assistant/memory/settings', json={'enabled': edit['enabled'], 'expectedRevision': memory['revision']}))
                if 'markdown' in edit:
                    checked(await client.put('/api/v1/assistant/memory/document', json={'markdown': edit['markdown'], 'expectedRevision': memory['revision']}))
            began = loop.time()
            submitted = admitted = None
            recovered = receipt is not None
            tracked = []

            def progress(event):
                append_row(directory / 'events.jsonl', {'case': case['id'], 'turn': index + 1, **event})
                if event.get('receipt'):
                    tracked.append(event['receipt'])

            try:
                if not receipt:
                    body = {'text': prompt, 'attachmentIds': [], **({'conversationId': conversation} if conversation else {'newConversation': True, 'personaId': case.get('persona', 'professional')})}
                    if index == 0:
                        for filename in case.get('attachments', []):
                            path = materials / filename
                            with path.open('rb') as stream:
                                upload = checked(await client.post('/api/v1/uploads', files={'file': (path.name, stream, mimetypes.guess_type(path.name)[0] or 'application/octet-stream')}), (200, 201))
                            body['attachmentIds'].append(upload['id'])
                    submitted = loop.time()
                    receipt = checked(await client.post('/api/v1/messages', json=body, headers={'Idempotency-Key': str(uuid4())}), (202,))
                    admitted = loop.time()
                append_row(directory / 'accepted.jsonl', {'case': case['id'], 'turn': index + 1, 'receipt': receipt, 'recovered': recovered})
                tracked.append(receipt)
                conversation = receipt['conversationId']
                if case.get('cancelFirst') and index == 0 and not recovered:
                    await asyncio.sleep(1)
                    job = checked(await client.get('/api/v1/jobs/' + receipt['jobId']))
                    checked(await client.post('/api/v1/jobs/' + receipt['jobId'] + '/cancel', json={'expectedAttempt': job['attempt'], 'expectedFence': job['fence']}))
                value, approvals = await settle(client, receipt, timeout, approve=case.get('approveActions', False), progress=progress)
                terminal_observed = loop.time()
                row = {'case': case['id'], 'turn': index + 1, 'prompt': prompt, 'receipt': receipt, 'message': value, 'approvals': approvals, 'files': await files(client, value, directory / 'files' / str(index + 1)), 'readback': await snapshot(client), 'seconds': round(loop.time() - began, 2), 'classification': 'review-required', 'recoveredAdmission': recovered}
                row['measurement'] = {
                    'preSendUploadSeconds': round(submitted - began, 4) if submitted is not None else None,
                    'admissionSeconds': round(admitted - submitted, 4) if admitted is not None else None,
                    'sendToTerminalSeconds': round(terminal_observed - submitted, 4) if submitted is not None else None,
                    'acceptedToTerminalSeconds': round(terminal_observed - admitted, 4) if admitted is not None else None,
                    'harnessDownloadReadbackSeconds': round(loop.time() - terminal_observed, 4),
                    'basis': 'HTTP send to polling terminal observation; excludes pre-send uploads and post-result validation; not browser paint',
                }
            except Exception as error:
                row = {'case': case['id'], 'turn': index + 1, 'prompt': prompt, 'receipt': receipt, 'exception': type(error).__name__, 'detail': str(error)[:500], 'seconds': round(loop.time() - began, 2), 'classification': 'incomplete'}
                row['cleanup'] = []
                for reference in reversed(tracked):
                    try:
                        job = checked(await client.get('/api/v1/jobs/' + reference['jobId']))
                        observed = {key: job.get(key) for key in ('id', 'state', 'attempt', 'fence')}
                        row['cleanup'].append({'before': observed})
                        progress({'kind': 'cleanup-before', 'job': observed})
                        if job['state'] in ('queued', 'running'):
                            response = await client.post('/api/v1/jobs/' + reference['jobId'] + '/cancel', json={'expectedAttempt': job['attempt'], 'expectedFence': job['fence']})
                            row['cleanup'][-1]['status'] = response.status_code
                    except Exception as cleanup_error:
                        row['cleanup'].append({'jobId': reference['jobId'], 'error': type(cleanup_error).__name__})
            append_row(first, row)
            print(json.dumps({'case': case['id'], 'turn': index + 1, 'state': row.get('message', {}).get('job', {}).get('state'), 'error': row.get('exception'), 'seconds': row['seconds']}, ensure_ascii=False), flush=True)
            rows.append(row)
            if row.get('exception') or row.get('message', {}).get('job', {}).get('state') in ('failed', 'awaiting_retry'):
                break
        result = {'case': case, 'turns': rows, 'before': before, 'after': await snapshot(client), 'classification': 'review-required'}
        (directory / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
        await client.post('/api/v1/auth/logout', json={})
        return result


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--metadata')
    source.add_argument('--state', help='Legacy private credentials linked to an adjacent owned manifest')
    parser.add_argument('--cases', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--materials')
    parser.add_argument('--group', choices=('development', 'holdout', 'all'))
    parser.add_argument('--ids', default='')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--continue-from', help='Read immutable prior results and recover unfinished turns into a new output directory')
    parser.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args()
    if args.metadata and not args.materials:
        parser.error('--materials is required with --metadata')
    _, meta, state = runner_environment(metadata_path=args.metadata, state_path=args.state)
    args.group = args.group or ('all' if args.state else 'development')
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    frozen = Path(args.cases)
    fingerprint = hashlib.sha256(frozen.read_bytes()).hexdigest()
    run = {'caseSha256': fingerprint, 'schema': meta['schema'], 'runId': meta['runId'], 'channel': 'http', 'group': args.group, 'ids': args.ids, 'requestLimit': None}
    previous = Path(args.continue_from).resolve() if args.continue_from else None
    if previous:
        if args.state or previous == output.resolve():
            raise RuntimeError('Continuation requires metadata and a separate output directory')
        original_run = json.loads((previous / 'run.json').read_text())
        if any(original_run.get(key) != run[key] for key in ('caseSha256', 'schema', 'runId', 'channel', 'group')):
            raise RuntimeError('Continuation must use the original frozen cases and owned environment')
        run['continuedFrom'] = str(previous)
    marker = output / 'run.json'
    if marker.exists():
        if not args.resume or json.loads(marker.read_text()) != run:
            raise RuntimeError('Existing run must match with explicit resume')
    else:
        marker.write_text(json.dumps(run, indent=2))
    cases = [case for case in json.loads(frozen.read_text()) if case.get('channel', 'http' if args.state else '') == 'http' and (args.group == 'all' or bool(case.get('holdout')) == (args.group == 'holdout')) and (not args.ids or case['id'] in args.ids.split(','))]
    if not cases:
        raise RuntimeError('No matching cases')
    if previous:
        plan = []
        for case in cases:
            rows = read_rows(previous / case['id'] / 'first.jsonl')
            done = [row['turn'] for row in rows if not row.get('exception') and row.get('message')]
            plan.append({'case': case['id'], 'role': case['role'], 'completedTurns': done, 'remainingTurns': [index + 1 for index in range(len(case['turns'])) if index + 1 not in done]})
        (output / 'recovery-plan.json').write_text(json.dumps(plan, indent=2))
    if args.state:
        records = output / 'first.jsonl'
        if records.exists():
            raise RuntimeError('Refusing to overwrite legacy first results')
        for original in cases:
            case = {'role': 'realApiEmployee', 'mode': 'full', **original}
            result = await execute_case(case, state, output, Path(args.materials or '.'), args.timeout)
            with records.open('a') as stream:
                for row in result['turns']:
                    stream.write(json.dumps(row, ensure_ascii=False) + '\n')
            result['evidence'] = {label: {'status': result['after'][key]['status'], 'body': {'items': result['after'][key].get('items', []), 'nextCursor': None}}
                                  for label, key in (('work', 'work'), ('reports', 'weekly'))}
            (output / (case['id'] + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2))
        return
    # Account-wide settings may change only between this actor's journeys.
    async def actor_cases(role):
        for case in cases:
            if case['role'] == role:
                if args.resume and (output / case['id'] / 'first.jsonl').exists():
                    continue
                prior = previous / case['id'] if previous else None
                rows = read_rows(prior / 'first.jsonl') if prior else []
                if rows and (len(rows) == len(case['turns']) and all(not row.get('exception') for row in rows) or rows[-1].get('message', {}).get('job', {}).get('state') in ('failed', 'awaiting_retry')):
                    continue
                try:
                    await execute_case(case, state, output, Path(args.materials), args.timeout, previous=prior)
                except Exception as error:
                    directory = output / case['id']
                    directory.mkdir(parents=True, exist_ok=True)
                    (directory / 'setup-failure.json').write_text(json.dumps({'case': case['id'], 'exception': type(error).__name__, 'detail': str(error)[:500]}, indent=2))
                    print(json.dumps({'case': case['id'], 'setupError': type(error).__name__}), flush=True)
                    return False
        return True
    # A failure for one actor must not cancel another actor's admitted request
    # before its receipt/result can be persisted.
    outcomes = await asyncio.gather(*(actor_cases(role) for role in sorted({case['role'] for case in cases})))
    if not all(outcomes):
        raise RuntimeError('An actor stopped at a recorded setup failure; other actors were allowed to settle')


if __name__ == '__main__':
    asyncio.run(main())
