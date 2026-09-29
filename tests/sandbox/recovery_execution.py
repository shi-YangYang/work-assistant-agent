"""Opt-in destructive control restart/queue/lease test on the local test service."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4
from real_execution import Runner


async def main():
    runner = Runner()
    name = os.environ.get('SANDBOX_TEST_CONTROL_CONTAINER')
    if name != 'noria-spec042-control':
        raise RuntimeError('Only the disposable Spec 042 control container may be restarted')
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
        command('kill', '--signal', 'KILL', name)
        command('start', name)
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
        while states.count('running') != 2:
            await asyncio.sleep(.1); states = [(await runner.client.get('/executions/'+row['id'])).json()['state'] for row in first]
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
    path = Path('artifacts/spec042/sandbox-recovery.json')
    path.write_text(json.dumps(runner.results, ensure_ascii=False, indent=2))
    return all(row['pass'] for row in runner.results)


if __name__ == '__main__':
    raise SystemExit(0 if asyncio.run(main()) else 1)
