"""Cancel only receipts in the current owned trial and terminate owned subprocesses."""
import asyncio
import json
import os
import signal
from pathlib import Path


async def terminate_process(process):
    if process.returncode is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), 5)
        except asyncio.TimeoutError:
            os.killpg(process.pid, signal.SIGKILL)
            await process.wait()


async def cleanup_owned(directory):
    from .adapters import environment
    import httpx
    metadata = directory / 'environment/metadata.json'
    if not metadata.exists():
        candidates = list(directory.rglob('environment/metadata.json'))
        if len(candidates) == 1:
            metadata = candidates[0]
    if not metadata.exists():
        return {'status': 'INCOMPLETE' if list(directory.rglob('accepted.jsonl')) else 'not-admitted', 'jobs': []}
    _, _, state = environment(metadata)
    receipts = {}
    for path in directory.rglob('accepted.jsonl'):
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if row.get('receipt'):
                receipts[row['receipt']['messageId']] = row['receipt']
    jobs = {r['jobId'] for r in receipts.values()}
    proven = {}
    errors = []
    for account in state['users'].values():
        try:
            async with httpx.AsyncClient(base_url=state['apiOrigin'], headers={'Origin': state['origin']}, timeout=10) as client:
                response = await client.post('/api/v1/auth/login', json={'username': account['username'], 'password': account['password']})
                response.raise_for_status()
                client.headers['X-CSRF-Token'] = response.json()['csrf']
                for receipt in receipts.values():
                    response = await client.get('/api/v1/messages/' + receipt['messageId'])
                    if response.status_code != 200:
                        continue
                    proven['message:' + receipt['messageId']] = True
                    for card in response.json().get('actions', []):
                        for value in (card.get('job') or {}, card.get('continuation') or {}):
                            if value.get('id') or value.get('jobId'):
                                jobs.add(value.get('jobId') or value['id'])
                for identifier in jobs:
                    response = await client.get('/api/v1/jobs/' + identifier)
                    if response.status_code != 200:
                        continue
                    job = response.json()
                    if job['state'] in ('queued', 'running'):
                        response = await client.post('/api/v1/jobs/' + identifier + '/cancel', json={'expectedAttempt': job['attempt'], 'expectedFence': job['fence']})
                        response.raise_for_status()
                        response = await client.get('/api/v1/jobs/' + identifier)
                        response.raise_for_status()
                        job = response.json()
                    if job['state'] in ('succeeded', 'failed', 'cancelled'):
                        proven[identifier] = job['state']
                await client.post('/api/v1/auth/logout', json={})
        except Exception as error:
            errors.append(type(error).__name__)
    complete = all(j in proven for j in jobs) and all('message:' + r['messageId'] in proven for r in receipts.values())
    return {'status': 'cleaned' if complete and (receipts or not errors) else 'INCOMPLETE', 'jobs': [{'job': j, 'after': proven.get(j)} for j in sorted(jobs)], 'errors': errors}


def partial_result(directory):
    turns, accepted = [], []
    for path in directory.rglob('result.json'):
        try:
            value = json.loads(path.read_text())
            if len(value.get('turns', [])) > len(turns):
                turns = value['turns']
        except (ValueError, OSError):
            pass
    for path in directory.rglob('first.jsonl'):
        try:
            observed = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
            if len(observed) > len(turns):
                turns = observed
        except (ValueError, OSError):
            pass
    for path in directory.rglob('accepted.jsonl'):
        for line in path.read_text().splitlines():
            try:
                accepted.append(json.loads(line))
            except ValueError:
                pass
    return {'turns': turns, 'accepted': accepted}


async def bounded_trial(operation, stopped, timeout, directory):
    task = asyncio.create_task(operation)
    interruption = asyncio.create_task(stopped.wait())
    failure = None
    completed = {}
    try:
        done, _ = await asyncio.wait((task, interruption), timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            completed = await task
            if completed.get('error') or completed.get('exitCode', 0) != 0 or any(r.get('exception') for r in completed.get('turns', [])):
                failure = 'partial-execution-error'
            else:
                return completed
        else:
            failure = 'cancelled' if stopped.is_set() else 'timeout'
    except asyncio.CancelledError:
        failure = 'cancelled'
    except Exception as error:
        failure = type(error).__name__
    finally:
        task.cancel()
        interruption.cancel()
        await asyncio.gather(task, interruption, return_exceptions=True)
        if failure:
            try:
                cleanup = await asyncio.wait_for(cleanup_owned(directory), 60)
            except Exception as error:
                cleanup = {'status': 'INCOMPLETE', 'error': type(error).__name__}
    return {**partial_result(directory), **completed, 'execution': 'INCOMPLETE', 'reason': failure, 'cleanup': cleanup}
