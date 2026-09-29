"""Bounded opt-in real-HTTP load against an owned isolated API (no models).

Frozen budget: 100/1,000/10,000 work and message rows; 1/10/25 concurrent
clients with 100 requests each, 80 reads + 20 writes. First-page p95 < 3s,
HTTP mixed p95 < 5s, zero errors, response < 64 KiB, API RSS < 512 MiB.
Query sample budget <= 6 SQL statements. No cloud capacity claim is made.
"""
import argparse
import asyncio
from datetime import timedelta
import json
import math
import os
from pathlib import Path
import platform
import socket
import statistics
import subprocess
import sys
import time
from uuid import uuid4

from environment import ROOT, load_environment


def distribution(values):
    ordered = sorted(values)
    return {'p50Ms': round(statistics.median(ordered), 2), 'p95Ms': round(ordered[math.ceil(len(ordered) * .95) - 1], 2)}


def rss(pid):
    result = subprocess.run(['ps', '-o', 'rss=', '-p', str(pid)], capture_output=True, text=True)
    return int(result.stdout.strip() or 0) * 1024


async def run(args):
    metadata, private = load_environment(args.metadata)
    os.environ.update(private['environment'])
    import httpx
    from sqlalchemy import event, func, select
    from app.core.config import Settings
    from app.db.base import now
    from app.db import registry
    from app.db.session import database
    from app.modules.members.models import Member
    from app.modules.messages.models import Message
    from app.modules.work.models import WorkItem
    from app.modules.work.queries import work_page
    from app.tasks.models import Job
    from urllib.parse import urlsplit
    settings = Settings()
    origin = metadata['apiOrigin']
    address = urlsplit(origin)
    if address.hostname != '127.0.0.1' or address.port != 8017 or metadata['purpose'] != 'load':
        raise RuntimeError('Load only runs in the owned load environment at 127.0.0.1:8017')
    with socket.socket() as probe:
        probe.bind((address.hostname, address.port))
    engine, sessions = database(settings)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    plan = {'commit': metadata['commit'], 'schema': metadata['schema'], 'machine': {'system': platform.platform(), 'logicalCpus': os.cpu_count(), 'processor': platform.processor()},
            'budget': {'rows': [100, 1000, 10000], 'concurrency': [1, 10, 25], 'requestsPerLevel': 100, 'writeRequestsPerLevel': 20, 'querySamples': 5, 'queryP95Ms': 3000, 'mixedP95Ms': 5000, 'maxResponseBytes': 65536, 'maxApiRssBytes': 512 * 1024 * 1024, 'maxSqlStatements': 6, 'levelTimeoutSeconds': 60},
            'mode': 'real HTTP + PostgreSQL; deterministic data; no model provider',
            'measurementScope': {'sqlStatements': 'Direct work_page query, excluding HTTP auth/middleware', 'poolCheckedOutAfter': 'Inspector engine, not API subprocess'}, 'results': []}
    output.with_suffix('.plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    async with sessions() as db:
        original = await db.get(Member, private['accounts']['employee']['id'])
        hashed = original.password_hash
    users = []
    for count in plan['budget']['rows']:
        async with sessions.begin() as db:
            member = Member(company_id=original.company_id, username='load_' + uuid4().hex, name=f'固定样本{count}', role='employee', password_hash=hashed)
            db.add(member)
            await db.flush()
            stamp = now()
            for start in range(0, count, 1000):
                db.add_all(WorkItem(company_id=member.company_id, owner_id=member.id, title=f'工作 {i:05d}', content={'title': f'工作 {i:05d}', 'summary': '末尾检索标记' if i == count - 1 else '固定合成内容', 'status': 'blocked' if i % 3 == 0 else 'in_progress'}, updated_at=stamp - timedelta(seconds=i)) for i in range(start, min(start + 1000, count)))
                db.add_all(Message(company_id=member.company_id, owner_id=member.id, text=f'历史消息 {i:05d}', created_at=stamp - timedelta(seconds=i)) for i in range(start, min(start + 1000, count)))
                await db.flush()
            users.append((count, member))
    log = output.with_suffix('.api.log').open('w')
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', address.hostname, '--port', str(address.port)], cwd=ROOT, env=os.environ.copy(), stdout=log, stderr=subprocess.STDOUT)
    peak_rss = 0
    try:
        async with httpx.AsyncClient(base_url=origin, timeout=20, headers={'Origin': metadata['origin']}) as client:
            for _ in range(150):
                if process.poll() is not None:
                    raise RuntimeError('Owned load API stopped during startup')
                try:
                    if (await client.get('/api/v1/health')).status_code == 200:
                        break
                except httpx.ConnectError:
                    pass
                await asyncio.sleep(.1)
            else:
                raise RuntimeError('Owned API startup timed out')
            baseline_rss = rss(process.pid)
            for count, actor in users:
                login = await client.post('/api/v1/auth/login', json={'username': actor.username, 'password': private['accounts']['employee']['password']})
                assert login.status_code == 200
                client.headers['X-CSRF-Token'] = login.json()['csrf']
                durations, sizes, statements = [], [], []
                for _ in range(5):
                    began = time.perf_counter()
                    response = await client.get('/api/v1/work-items')
                    durations.append((time.perf_counter() - began) * 1000)
                    assert response.status_code == 200 and len(response.json()['items']) == 20
                    sizes.append(len(response.content))
                    sql_count = [0]
                    def before(*_):
                        sql_count[0] += 1
                    event.listen(engine.sync_engine, 'before_cursor_execute', before)
                    try:
                        async with sessions() as db:
                            page = await work_page(db, actor, actor.id)
                            assert len(page['items']) == 20
                    finally:
                        event.remove(engine.sync_engine, 'before_cursor_execute', before)
                    statements.append(sql_count[0])
                search = await client.get('/api/v1/work-items', params={'q': '末尾检索标记'})
                assert search.status_code == 200 and len(search.json()['items']) == 1
                assert search.json()['items'][0]['title'] == f'工作 {count - 1:05d}'
                totals = {}
                for endpoint in ('work-items', 'messages'):
                    cursor, seen, pages = None, set(), 0
                    while True:
                        response = await client.get('/api/v1/' + endpoint, params={'cursor': cursor} if cursor else {})
                        assert response.status_code == 200
                        data = response.json()
                        ids = {row['id'] for row in data['items']}
                        assert len(ids) == len(data['items']) and not (ids & seen)
                        seen.update(ids)
                        pages += 1
                        cursor = data['nextCursor']
                        if not cursor:
                            break
                        assert pages <= count
                    assert len(seen) == count
                    totals[endpoint] = {'rows': len(seen), 'pages': pages, 'duplicates': 0}
                measurement = {'type': 'query', 'rows': count, **distribution(durations), 'responseBytes': sizes, 'sqlStatements': statements, 'pagination': totals, 'searchLastRow': True}
                assert measurement['p95Ms'] < 3000 and max(sizes) < 65536 and max(statements) <= 6
                plan['results'].append(measurement)
                peak_rss = max(peak_rss, rss(process.pid))
            actor = users[-1][1]
            for concurrency in (1, 10, 25):
                semaphore = asyncio.Semaphore(concurrency)
                times, codes = [], []
                async def request(index):
                    async with semaphore:
                        start = time.perf_counter()
                        if index % 5 == 0:
                            response = await client.post('/api/v1/work-items', json={'title': f'并发{concurrency}-{index}', 'summary': '有界写入', 'status': 'in_progress'}, headers={'Idempotency-Key': str(uuid4())})
                            assert response.status_code == 201, response.status_code
                            assert response.json()['title'] == f'并发{concurrency}-{index}'
                        else:
                            response = await client.get('/api/v1/work-items', params={'q': '固定合成内容'})
                            assert response.status_code == 200 and len(response.json()['items']) == 20
                        times.append((time.perf_counter() - start) * 1000)
                        codes.append(response.status_code)
                await asyncio.wait_for(asyncio.gather(*(request(i) for i in range(100))), 60)
                async with sessions() as db:
                    written = await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id == actor.id, WorkItem.title.like(f'并发{concurrency}-%')))
                assert written == 20
                measurement = {'type': 'mixed', 'concurrency': concurrency, 'requests': len(codes), 'failures': 0, 'writesPersisted': written, **distribution(times)}
                assert measurement['p95Ms'] < 5000
                plan['results'].append(measurement)
                peak_rss = max(peak_rss, rss(process.pid))
            jobs = []
            for index in range(25):
                response = await client.post('/api/v1/messages', json={'text': f'待取消{index}', 'newConversation': True}, headers={'Idempotency-Key': str(uuid4())})
                assert response.status_code == 202
                jobs.append(response.json()['jobId'])
            async def cancel(identifier):
                response = await client.post(f'/api/v1/jobs/{identifier}/cancel', json={'expectedAttempt': 0, 'expectedFence': 0})
                assert response.status_code == 200 and response.json()['state'] == 'cancelled'
            await asyncio.gather(*(cancel(identifier) for identifier in jobs))
            async with sessions() as db:
                states = (await db.execute(select(Job.state, func.count()).where(Job.id.in_(jobs)).group_by(Job.state))).all()
            assert dict(states) == {'cancelled': 25}
            plan['results'].append({'type': 'queue-cancel', 'queued': 25, 'cancelled': 25, 'remainingActive': 0})
            await asyncio.sleep(2)
            plan['resources'] = {'apiPid': process.pid, 'baselineRssBytes': baseline_rss, 'peakSampledRssBytes': peak_rss, 'afterRssBytes': rss(process.pid), 'poolCheckedOutAfter': engine.pool.checkedout(), 'note': 'RSS allocator retention is recorded; no invented return-to-baseline threshold.'}
            assert peak_rss < 512 * 1024 * 1024 and engine.pool.checkedout() == 0
        plan['status'] = 'PASS'
    except BaseException as error:
        plan['status'] = 'FAIL'
        plan['failureType'] = type(error).__name__
        raise
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log.close()
        plan['ownedApiStopped'] = process.poll() is not None
        output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n')
        await engine.dispose()
    print(json.dumps({'status': plan['status'], 'cases': len(plan['results']), 'output': str(output)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', required=True)
    parser.add_argument('--output', default='artifacts/spec044/server/load-results.json')
    asyncio.run(run(parser.parse_args()))
