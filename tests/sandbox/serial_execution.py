"""Opt-in single-slot fairness and queue cancellation against a disposable control."""
import asyncio
import json
from pathlib import Path
from real_execution import Runner


async def main():
    runner = Runner()
    assert (await runner.client.get('/health')).json()['concurrency'] == 1
    bodies = []
    try:
        for index, owner in enumerate(['a', 'a', 'a', 'b', 'b', 'c', 'c']):
            body = await runner.submit(f'import time;time.sleep(.7);print("{owner}{index}")', owner=owner)
            bodies.append((body, owner))
        cancelled = await runner.submit("raise AssertionError('queue cancellation failed')", owner='d')
        assert (await runner.client.post('/executions/'+cancelled['id']+'/cancel')).json()['state'] == 'cancelled'
        order, maximum = [], 0
        async with asyncio.timeout(30):
            while len(order) < len(bodies):
                running = 0
                for body, owner in bodies:
                    value = (await runner.client.get('/executions/'+body['id'])).json()
                    running += value['state'] == 'running'
                    if value['state'] == 'succeeded' and body['id'] not in [item[0] for item in order]: order.append((body['id'], owner))
                    assert value['state'] in ('queued','running','succeeded'), value
                maximum = max(maximum, running)
                await asyncio.sleep(.05)
        assert maximum == 1
        # All three queued owners get a turn before any can drain all 3 jobs.
        assert set(owner for _,owner in order[:4]) == {'a','b','c'}, order
        assert (await runner.wait(cancelled['id']))['state'] == 'cancelled'
        result = {'pass': True, 'concurrency':maximum, 'completedOwnerOrder':[owner for _,owner in order], 'queuedCancel':'never executed'}
        Path('artifacts/spec042/sandbox-serial.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    finally:
        for identifier in runner.ids:await runner.client.delete('/executions/'+identifier)
        await runner.client.aclose()


if __name__ == '__main__': asyncio.run(main())
