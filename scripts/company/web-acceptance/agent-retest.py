"""Bounded real API/worker regressions; never invokes an agent harness directly."""
import argparse
import asyncio
import hashlib
import importlib.util
import json
import time
from pathlib import Path
from uuid import uuid4

import httpx

spec = importlib.util.spec_from_file_location('acceptance_agent_http', Path(__file__).with_name('agent-http.py'))
agent_http = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent_http)


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


async def business_snapshot(client):
    result = {}
    for name, path, params in (
        ('work', '/api/v1/work-items', {}),
        ('dailyReports', '/api/v1/reports', {'kind': 'daily'}),
        ('weeklyReports', '/api/v1/reports', {'kind': 'weekly'}),
    ):
        response = await agent_http.read_pages(client, path, **params)
        if response['status'] != 200:
            raise RuntimeError('Business snapshot failed: ' + name + ' ' + str(response['status']))
        result[name] = response['body']['items']
    return result


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True)
    parser.add_argument('--cases', default=str(Path(__file__).with_name('retest-cases.json')))
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    state_path = Path(args.state)
    if state_path.stat().st_mode & 0o077:
        raise RuntimeError('Private credentials required')
    state = json.loads(state_path.read_text())
    if not state['schema'].startswith('spec044_web_') or state['apiOrigin'] != 'http://127.0.0.1:8016':
        raise RuntimeError('Isolated acceptance API only')
    cases = json.loads(Path(args.cases).read_text())
    if not 1 <= sum(len(case['turns']) for case in cases) <= 12 or len(cases) > 6:
        raise RuntimeError('At most six cases and twelve user messages')
    if len({case['id'] for case in cases}) != len(cases) or any(case['role'] != 'realApiEmployee' for case in cases):
        raise RuntimeError('Unique case ids and designated synthetic employee required')
    output = Path(args.output)
    if output.exists():
        raise RuntimeError('Refusing to overwrite any prior run')
    output.mkdir(parents=True)
    write_json(output / 'cases.json', cases)
    user = state['users']['realApiEmployee']
    async with httpx.AsyncClient(base_url=state['apiOrigin'], headers={'Origin': state['origin']}, timeout=30) as client:
        login = await client.post('/api/v1/auth/login', json={'username': user['username'], 'password': user['password']})
        login.raise_for_status()
        client.headers['X-CSRF-Token'] = login.json()['csrf']
        try:
            for case in cases:
                conversation = None
                case_before = await business_snapshot(client)
                evidence = {'case': case, 'before': case_before, 'turns': [], 'classification': 'review-required'}
                write_json(output / (case['id'] + '.json'), evidence)
                if case.get('seedWork'):
                    seed = case['seedWork']
                    if not seed.get('title', '').startswith('回归044-') or set(seed) - {'title', 'summary', 'status', 'blocker', 'nextStep', 'dueDate'}:
                        raise RuntimeError('Only an explicit regression work fixture can be seeded')
                    if any(work['title'] == seed['title'] for work in case_before['work']):
                        raise RuntimeError('Seed work already exists; refusing duplicate preparation')
                    prepared = await client.post('/api/v1/work-items', json=seed, headers={'Idempotency-Key': str(uuid4())})
                    prepared.raise_for_status()
                    evidence['preparation'] = {'type': 'manual-http-work-fixture', 'countsAsAgentSuccess': False, 'work': prepared.json()}
                    evidence['before'] = await business_snapshot(client)
                    write_json(output / (case['id'] + '.json'), evidence)
                for index, prompt in enumerate(case['turns'], 1):
                    started = time.monotonic()
                    body = {'text': prompt, 'attachmentIds': []}
                    if conversation:
                        body['conversationId'] = conversation
                    else:
                        body.update(newConversation=True, personaId='professional', executionMode=case['mode'])
                        if case['mode'] == 'full':
                            body['fullAccessConfirmed'] = True
                        for filename in case.get('attachments', []):
                            path = Path(filename)
                            with path.open('rb') as stream:
                                upload = await client.post('/api/v1/uploads', files={'file': (path.name, stream)})
                            upload.raise_for_status()
                            body['attachmentIds'].append(upload.json()['id'])
                    row = {'case': case['id'], 'turn': index, 'prompt': prompt, 'classification': 'review-required'}
                    try:
                        sent = await client.post('/api/v1/messages', json=body, headers={'Idempotency-Key': str(uuid4())})
                        sent.raise_for_status()
                        row['receipt'] = receipt = sent.json()
                        conversation = receipt['conversationId']
                        with (output / 'submitted.jsonl').open('a') as stream:
                            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
                        async with asyncio.timeout(300):
                            while True:
                                response = await client.get('/api/v1/messages/' + receipt['messageId'])
                                response.raise_for_status()
                                message = response.json()
                                if message.get('job', {}).get('state') in agent_http.TERMINAL:
                                    break
                                await asyncio.sleep(1)
                        row['message'] = message
                        row['files'] = []
                        for deliverable in message.get('deliverables', []):
                            for file in deliverable.get('files', []):
                                if not file['url'].startswith('/api/v1/'):
                                    raise RuntimeError('Unexpected download URL')
                                response = await client.get(file['url'])
                                response.raise_for_status()
                                data = response.content
                                destination = output / 'files' / case['id'] / str(index)
                                destination.mkdir(parents=True, exist_ok=True)
                                name = Path(file['name']).name
                                target = destination / name
                                if target.exists():
                                    target = destination / (str(len(row['files'])) + '-' + name)
                                target.write_bytes(data)
                                row['files'].append({'name': name, 'path': str(target), 'size': len(data),
                                                     'declaredSize': file['size'], 'sha256': hashlib.sha256(data).hexdigest(),
                                                     'text': data.decode('utf-8-sig', errors='replace') if target.suffix in ('.txt', '.md', '.csv') else None})
                        row['businessAfter'] = await business_snapshot(client)
                        changed = [item for item in row['businessAfter']['work'] if item.get('title', '').startswith('回归044')]
                        row['workDetails'] = []
                        for item in changed:
                            response = await client.get('/api/v1/work-items/' + item['id'])
                            response.raise_for_status()
                            row['workDetails'].append(response.json())
                    except Exception as error:
                        row.update(exception=type(error).__name__, detail=str(error)[:300], classification='incomplete')
                    row['seconds'] = round(time.monotonic() - started, 2)
                    evidence['turns'].append(row)
                    write_json(output / (case['id'] + '.json'), evidence)
                    with (output / 'first.jsonl').open('a') as stream:
                        stream.write(json.dumps(row, ensure_ascii=False) + '\n')
                    print(json.dumps({'case': case['id'], 'turn': index, 'state': row.get('message', {}).get('job', {}).get('state'), 'exception': row.get('exception'), 'seconds': row['seconds']}, ensure_ascii=False), flush=True)
                    if row.get('exception') or row.get('message', {}).get('job', {}).get('state') in ('failed', 'cancelled', 'awaiting_retry'):
                        evidence['stoppedAfterFailure'] = True
                        write_json(output / (case['id'] + '.json'), evidence)
                        break
        finally:
            await client.post('/api/v1/auth/logout', json={})


if __name__ == '__main__':
    asyncio.run(main())
