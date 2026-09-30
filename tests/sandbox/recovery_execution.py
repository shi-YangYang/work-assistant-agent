"""Opt-in destructive control restart/queue/lease test on the local test service."""
import asyncio
import json
import os
import re
from urllib.parse import urlsplit
from pathlib import Path
import subprocess
from real_execution import Runner


def isolated_control():
    """Resolve only an explicitly named, labelled disposable local test control."""
    name = os.environ.get('SANDBOX_TEST_CONTROL_CONTAINER', '')
    project = os.environ.get('SANDBOX_TEST_COMPOSE_PROJECT', '')
    address = urlsplit(os.environ.get('SANDBOX_TEST_URL', ''))
    if os.environ.get('SPEC042_SANDBOX_TEST') != '1' or not re.fullmatch(r'noria-spec[0-9]{3}(?:-[a-z0-9-]+)?', project):
        raise RuntimeError('Explicit disposable Compose test project is required')
    if name != project + '-control' or address.scheme != 'http' or address.hostname != '127.0.0.1' or not address.port or address.port == 8011:
        raise RuntimeError('Refusing a non-test control name, origin or ordinary 8011 service')
    result = subprocess.run(['docker', 'inspect', name], check=True, capture_output=True, text=True, timeout=10)
    container = json.loads(result.stdout)[0]
    labels = container['Config'].get('Labels') or {}
    if labels.get('com.docker.compose.project') != project or labels.get('com.docker.compose.service') != 'control':
        raise RuntimeError('Control Compose ownership label mismatch')
    ports = container['HostConfig'].get('PortBindings', {}).get('8010/tcp', [])
    if ports != [{'HostIp': '127.0.0.1', 'HostPort': str(address.port)}]:
        raise RuntimeError('Control published port does not match the test URL')
    volumes = {mount['Destination']: mount.get('Name', '') for mount in container['Mounts'] if mount['Type'] == 'volume'}
    if any(not volumes.get(target, '').startswith(project + '_') for target in ('/state', '/var/run')):
        raise RuntimeError('Control volumes are not scoped to the disposable project')
    return container['Id']


def report_path(default):
    path = Path(os.environ.get('SANDBOX_TEST_REPORT', default))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


async def main():
    control_id = isolated_control()
    runner = Runner()
    def command(*args):
        subprocess.run(['docker', *args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)
    async def crash_recover():
        retained = await runner.submit("print('retained')")
        assert (await runner.wait(retained['id']))['state'] == 'succeeded'
        jobs = [await runner.submit('import time;time.sleep(18)', owner=owner) for owner in ['a', 'b', 'c']]
        async with asyncio.timeout(15):
            while True:
                states = [(await runner.client.get('/executions/' + row['id'])).json()['state'] for row in jobs]
                if states.count('running') == 2 and states.count('queued') == 1: break
                await asyncio.sleep(.1)
        command('kill', '--signal', 'KILL', control_id)
        command('start', control_id)
        async with asyncio.timeout(30):
            while True:
                try:
                    if (await runner.client.get('/health')).status_code == 200: break
                except Exception: pass
                await asyncio.sleep(.3)
        for row in jobs:
            result = await runner.wait(row['id'])
            assert result['state'] == 'failed' and not result['files'], result
            replay = await runner.client.post('/executions', json=row)
            assert replay.json()['state'] == 'failed'
        assert (await runner.wait(retained['id']))['stdout'].strip() == 'retained'
        after = await runner.submit("print('recovered')")
        assert (await runner.wait(after['id']))['stdout'].strip() == 'recovered'
        return {'actualConcurrentRunning': 2, 'queued': 1, 'abruptControlDeath': 'reconciled', 'uncertainJobs': 'not replayed', 'completedReceipt': 'retained'}
    async def queue_and_cancel():
        first = [await runner.submit('import time;time.sleep(3)', owner=owner) for owner in ['a','b']]
        queued = await runner.submit("raise RuntimeError('must never run')", owner='c')
        states = [(await runner.client.get('/executions/'+row['id'])).json()['state'] for row in first]
        async with asyncio.timeout(15):
            while states.count('running') != 2:
                await asyncio.sleep(.1)
                states = [(await runner.client.get('/executions/'+row['id'])).json()['state'] for row in first]
        assert (await runner.client.get('/executions/'+queued['id'])).json()['state'] == 'queued'
        assert (await runner.client.post('/executions/'+queued['id']+'/cancel')).json()['state'] == 'cancelled'
        for row in first: assert (await runner.wait(row['id']))['state'] == 'succeeded'
        assert (await runner.wait(queued['id']))['state'] == 'cancelled'
        return {'twoRealRunningIntervalsOverlap': True, 'queuedCancel': 'never executed'}
    async def orphan():
        body = await runner.submit('import time;time.sleep(100)')
        # No heartbeat: the execution is cancelled after 45s, before runtime's
        # 60s deadline. Do not call GET until the reclaim deadline passes.
        await asyncio.sleep(47)
        result = await runner.wait(body['id'])
        assert result['state'] == 'cancelled' and not result['files'], result
        return {'noHeartbeatSeconds': 47, 'state': result['state']}
    try:
        await runner.case('abrupt-control-restart', crash_recover)
        await runner.case('real-parallel-queue-cancel', queue_and_cancel)
        await runner.case('orphan-reclaim', orphan)
    finally:
        for identifier in runner.ids:
            try: await runner.client.delete('/executions/'+identifier)
            except Exception: pass
        await runner.client.aclose()
    path = report_path('artifacts/spec042/sandbox-recovery.json')
    path.write_text(json.dumps(runner.results, ensure_ascii=False, indent=2))
    return all(row['pass'] for row in runner.results)


if __name__ == '__main__':
    raise SystemExit(0 if asyncio.run(main()) else 1)
