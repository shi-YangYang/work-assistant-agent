"""Compare HEAD implementations with current SQL on disposable test-company rows.

Run from the repository with PYTHONPATH=apps/server:packages/voiceprint-engine/src
.venv-server/bin/python scripts/benchmarks/company-queries.py. Never uses production.
"""
import argparse
import asyncio
import json
import math
import os
import statistics
import subprocess
import time
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import now
from app.db.registry import metadata
from app.db.session import database
from app.modules.members.models import Company, Member
from app.modules.messages.models import Message
from app.modules.model_services.models import ModelUsage
from app.modules.model_services.usage import usage_page
from app.modules.team.metrics import team_data
from app.modules.work.models import WorkItem, WorkRevision
from app.security.locks import company_lock

ROOT = Path(__file__).resolve().parents[2]


def baseline(path, function, revision):
    source = subprocess.check_output(['git', 'show', revision + ':' + path], cwd=ROOT, text=True)
    namespace = {'__name__': '_query_baseline'}
    exec(compile(source, path, 'exec'), namespace)
    return namespace[function]


def distribution(values):
    ordered = sorted(values)
    return {'p50Ms': round(statistics.median(ordered), 2), 'p95Ms': round(ordered[max(0, math.ceil(len(ordered) * .95) - 1)], 2)}


async def main(revision):
    from dataclasses import replace
    original = Settings()
    url = os.getenv('DATABASE_TEST_URL', '')
    if not url or make_url(url).database != 'paa_company_test':
        raise SystemExit('DATABASE_TEST_URL must name paa_company_test')
    settings = replace(original, database_url=url)
    engine, sessions = database(settings)
    company_id, owner_id = str(uuid4()), str(uuid4())
    stamp = now() - timedelta(minutes=5)
    count = 2000
    measurements = {'database': 'paa_company_test', 'rowsPerDataset': count, 'samples': 5, 'baseline': subprocess.check_output(['git', 'rev-parse', revision], cwd=ROOT, text=True).strip()}
    counters = {'queries': 0, 'ormRows': 0, 'active': False}
    def query(conn, cursor, statement, parameters, context, many):
        if counters['active']:
            counters['queries'] += 1
            context._benchmark_start = time.perf_counter()
    def query_end(conn, cursor, statement, parameters, context, many):
        if counters['active']:
            counters.setdefault('sqlMs', []).append(round((time.perf_counter() - context._benchmark_start) * 1000, 2))
    def loaded(*args):
        if counters['active']:
            counters['ormRows'] += 1
    event.listen(engine.sync_engine, 'before_cursor_execute', query)
    event.listen(engine.sync_engine, 'after_cursor_execute', query_end)
    event.listen(Session, 'loaded_as_persistent', loaded)
    try:
        async with sessions.begin() as db:
            db.add(Company(id=company_id, name='query-benchmark'))
            await db.flush()
            actor = Member(id=owner_id, company_id=company_id, username='bench_' + uuid4().hex, name='样本员工', role='employee')
            admin = Member(company_id=company_id, username='bench_' + uuid4().hex, name='样本管理员', role='admin')
            db.add_all([actor, admin])
            await db.flush()
            for index in range(count):
                instant = stamp - timedelta(seconds=index)
                content = {'title': f'样本{index}', 'summary': '固定样本', 'status': 'blocked', 'blocker': '等待', 'nextStep': ''}
                work = WorkItem(id=str(uuid4()), company_id=company_id, owner_id=owner_id, title=content['title'], content=content, updated_at=instant)
                db.add(work)
                db.add(WorkRevision(company_id=company_id, owner_id=owner_id, work_id=work.id, revision=1, content=content, source_ids=[], created_at=instant))
                db.add(Message(company_id=company_id, owner_id=owner_id, text='固定消息', created_at=instant))
                db.add(ModelUsage(company_id=company_id, owner_id=owner_id, kind='assistant', status='succeeded', started_at=instant, created_at=instant, service_name='固定服务', model_name='固定模型', elapsed_ms=100, actual_input_tokens=10, actual_output_tokens=20))
        # Seeded rows need current planner statistics before comparing plans.
        # This is only the guarded disposable test database, never production.
        async with engine.begin() as connection:
            for table in ('company_member', 'company_message', 'company_work_item', 'company_work_revision', 'company_model_usage'):
                await connection.execute(text('ANALYZE ' + table))
        measurements['plannerStatistics'] = 'ANALYZE after deterministic seed'
        cases = [('usage', baseline('apps/server/app/modules/model_services/usage.py', 'usage_page', revision), usage_page), ('team', baseline('apps/server/app/modules/team/metrics.py', 'team_data', revision), team_data)]
        for name, before, after in cases:
            outputs = []
            for label, implementation in [('before', before), ('after', after)]:
                timings, query_counts, rows = [], [], []
                for _ in range(5):
                    counters.update(active=True, queries=0, ormRows=0, sqlMs=[])
                    started = time.perf_counter()
                    async with sessions() as db:
                        result = await implementation(db, admin)
                    timings.append((time.perf_counter() - started) * 1000)
                    counters['active'] = False
                    query_counts.append(counters['queries'])
                    rows.append(counters['ormRows'])
                measurements[name + '-' + label] = {**distribution(timings), 'sqlStatements': query_counts, 'ormRowsLoaded': rows, 'lastSampleSqlMs': counters['sqlMs']}
                outputs.append(result)
            if name == 'usage':
                assert outputs[0] == outputs[1]
            else:
                assert outputs[0][0]['metrics'] == outputs[1][0]['metrics']
                assert outputs[0][0]['items'] == outputs[1][0]['items']
            measurements[name + '-equal'] = True
        for shared in (False, True):
            waits, totals = [], []
            for _ in range(5):
                async def reader():
                    async with sessions.begin() as db:
                        started = time.perf_counter()
                        await company_lock(db, company_id, shared=shared)
                        waits.append((time.perf_counter() - started) * 1000)
                        # Fixed held duration isolates lock behavior, not provider IO.
                        await asyncio.sleep(.05)
                started = time.perf_counter()
                await asyncio.gather(reader(), reader())
                totals.append((time.perf_counter() - started) * 1000)
            measurements['lock-' + ('shared' if shared else 'exclusive')] = {'wait': distribution(waits), 'twoReadersTotal': distribution(totals), 'heldMsPerReader': 50}
        output = ROOT / 'artifacts/spec030/company-queries.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(measurements, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(measurements, ensure_ascii=False, indent=2))
    finally:
        event.remove(Session, 'loaded_as_persistent', loaded)
        async with sessions.begin() as db:
            for table in reversed(metadata.sorted_tables):
                if 'company_id' in table.c:
                    await db.execute(table.delete().where(table.c.company_id == company_id))
            await db.execute(delete(Company).where(Company.id == company_id))
        await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default='HEAD', help='Git revision before the query changes')
    asyncio.run(main(parser.parse_args().baseline))
