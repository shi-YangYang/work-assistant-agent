"""Retry an existing failed report through the real API and preserve evidence."""
import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    path = Path(args.state)
    if path.stat().st_mode & 0o077:
        raise RuntimeError('Private credentials required')
    state = json.loads(path.read_text())
    if not state['schema'].startswith('spec044_web_') or state['apiOrigin'] != 'http://127.0.0.1:8016':
        raise RuntimeError('Isolated API only')
    target = Path(args.output)
    if target.exists():
        raise RuntimeError('Refusing to overwrite report retry evidence')
    baseline = json.loads(Path(args.baseline).read_text())
    reports = baseline['evidence']['reports']['body']['items']
    if len(reports) != 1 or reports[0]['job']['state'] not in ('failed', 'awaiting_retry'):
        raise RuntimeError('Expected one recorded failed report')
    report_id, job_id = reports[0]['id'], reports[0]['job']['id']
    user = state['users']['realApiEmployee']
    result = {'baseline': args.baseline, 'reportId': report_id, 'jobId': job_id, 'userMessages': 0, 'retryRequests': 1, 'classification': 'review-required'}
    target.parent.mkdir(parents=True, exist_ok=True)
    def save():
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    started = time.monotonic()
    async with httpx.AsyncClient(base_url=state['apiOrigin'], headers={'Origin': state['origin']}, timeout=30) as client:
        login = await client.post('/api/v1/auth/login', json={'username': user['username'], 'password': user['password']})
        login.raise_for_status()
        client.headers['X-CSRF-Token'] = login.json()['csrf']
        try:
            before = await client.get('/api/v1/reports/' + report_id)
            before.raise_for_status()
            result['before'] = before.json()
            save()
            retry = await client.post('/api/v1/jobs/' + job_id + '/retry', json={})
            result['retryResponse'] = {'status': retry.status_code, 'body': retry.json()}
            save()
            retry.raise_for_status()
            async with asyncio.timeout(300):
                while True:
                    response = await client.get('/api/v1/reports/' + report_id)
                    response.raise_for_status()
                    result['after'] = response.json()
                    if result['after']['job']['state'] in ('succeeded', 'failed', 'awaiting_retry', 'cancelled'):
                        break
                    await asyncio.sleep(1)
            result['seconds'] = round(time.monotonic() - started, 2)
            save()
            print(json.dumps({'case': 'R01-report-retry', 'state': result['after']['job']['state'], 'error': result['after']['job']['error'], 'seconds': result['seconds']}, ensure_ascii=False), flush=True)
        finally:
            await client.post('/api/v1/auth/logout', json={})


if __name__ == '__main__':
    asyncio.run(main())
