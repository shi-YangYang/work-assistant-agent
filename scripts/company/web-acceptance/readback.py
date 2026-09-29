"""Read final synthetic business data without re-running real-model requests."""
import argparse
import asyncio
import importlib.util
import json
from pathlib import Path

import httpx


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    state_path = Path(args.state)
    if state_path.stat().st_mode & 0o077:
        raise RuntimeError('Private credentials required')
    state = json.loads(state_path.read_text())
    if not state['schema'].startswith('spec044_web_') or state['apiOrigin'] != 'http://127.0.0.1:8016':
        raise RuntimeError('Isolated API only')
    output = Path(args.output)
    if output.exists():
        raise RuntimeError('Refusing to overwrite evidence')
    spec = importlib.util.spec_from_file_location('agent_http', Path(__file__).with_name('agent-http.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = {'scope': 'Read at collection time; does not replace per-turn historical evidence', 'roles': {}}
    for role in ('realApiAdmin', 'realApiEmployee', 'realAdmin', 'realEmployee'):
        user = state['users'][role]
        async with httpx.AsyncClient(base_url=state['apiOrigin'], headers={'Origin': state['origin']}) as client:
            response = await client.post('/api/v1/auth/login', json={'username': user['username'], 'password': user['password']})
            response.raise_for_status()
            client.headers['X-CSRF-Token'] = response.json()['csrf']
            work_response = await module.read_pages(client, '/api/v1/work-items')
            assert work_response['status'] == 200, work_response['status']
            work = work_response['body']['items']
            report_response = await module.read_pages(client, '/api/v1/reports', kind='weekly')
            assert report_response['status'] == (403 if user['role'] == 'admin' else 200)
            reports = report_response['body'].get('items', [])
            details = []
            for item in work:
                response = await client.get('/api/v1/work-items/' + item['id'])
                response.raise_for_status()
                details.append(response.json())
            result['roles'][role] = {'work': work, 'workDetails': details, 'reports': reports,
                                    'reportsStatus': report_response['status']}
            if user['role'] == 'admin':
                team = {}
                for label, path, params in (
                    ('summary', '/api/v1/team', {}),
                    ('blocked', '/api/v1/team/workspace/work', {'status': 'blocked'}),
                    ('reports', '/api/v1/team/workspace/reports', {'kind': 'weekly'}),
                ):
                    response = await client.get(path, params=params)
                    response.raise_for_status()
                    team[label] = response.json()
                result['roles'][role]['team'] = team
            await client.post('/api/v1/auth/logout', json={})
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print({role: {'work': len(value['work']), 'reports': len(value['reports'])} for role, value in result['roles'].items()})


if __name__ == '__main__':
    asyncio.run(main())
