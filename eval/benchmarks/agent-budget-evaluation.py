"""Opt-in real-model budget journeys, using disposable tenants in paa_company_test.

--runtime-root may point to an exported committed backend for a matched baseline.
Model configuration is read from the selected local account; business writes,
files, memory and checkpoints remain isolated. No inference grading or retries.
"""
import argparse
import asyncio
from dataclasses import replace
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-user', required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--runtime-root', type=Path, default=ROOT)
parser.add_argument('--ids', default='chat,research,business,file')
parser.add_argument('--effort', default='low')
args = parser.parse_args()
sys.path[:0] = [str(args.runtime_root / 'apps/server'), str(ROOT / 'tests/server'), str(ROOT / 'eval')]
from app.core.config import Settings
spec = importlib.util.spec_from_file_location('agent_evaluation', ROOT / 'eval/agent-evaluation.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
from app.modules.model_services.models import ModelUsage
from app.modules.work.models import WorkItem
from app.tasks.models import Job
from app.tasks.processing.handlers import process_job
from app.tasks.runtime.queue import claim
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import select, event
from sqlalchemy.engine import make_url

CASES = {
    'chat': ('employee', '请用三句话解释为什么开会前需要明确议题。'),
    'research': ('admin', '请联网查询Python、PostgreSQL和React三个项目官方介绍，分别打开至少一个官方网页，简要对比各自的用途并附来源链接。不要写入工作系统。'),
    'business': ('employee', '请创建工作“客户访谈准备”，内容写“整理访谈问题并预约三位客户”，然后给我三条实施建议，不要只回复创建成功。'),
    'file': ('employee', '请生成可下载的Excel：列为项目、金额，数据为甲100、乙200，附合计300。不要写入工作系统。'),
}


class Timings(logging.Handler):
    def __init__(self):
        super().__init__()
        self.rows = []
    def emit(self, record):
        message = record.getMessage()
        if message.startswith('latency '):
            self.rows.append(json.loads(message[8:]))


async def evaluate(identifier, configs):
    role, prompt = CASES[identifier]
    with tempfile.TemporaryDirectory(prefix='noria-budget-eval-') as directory:
        fixture = base.setup.__wrapped__(Path(directory))
        settings, sessions, users, clients = await anext(fixture)
        trace = Timings()
        log = logging.getLogger('paa.latency')
        log.addHandler(trace)
        sql = [0]
        engine = sessions.kw['bind']
        def statement(*_):
            sql[0] += 1
        event.listen(engine.sync_engine, 'before_cursor_execute', statement)
        try:
            await base.install_models(configs, settings, sessions, users[role].company_id)
            if identifier == 'file':
                local = Settings()
                if not local.sandbox_url or not local.sandbox_token:
                    return {'case': identifier, 'status': 'BLOCKED', 'reason': '本地沙盒未配置'}
                settings = replace(settings, sandbox_url=local.sandbox_url, sandbox_token=local.sandbox_token)
            client = clients[role]
            if identifier == 'business':
                mode = base.checked(await client.get('/api/v1/assistant/execution-settings'), 200)
                base.checked(await client.patch('/api/v1/assistant/execution-settings', json={
                    'executionMode': 'full', 'fullAccessConfirmed': True, 'expectedRevision': mode['modeRevision']}), 200)
            sql[0] = 0
            started, epoch = time.monotonic(), time.time() * 1000
            sent = base.checked(await client.post('/api/v1/messages', json={'text': prompt, 'newConversation': True}, headers={'Idempotency-Key': str(uuid4())}), 202)
            job = await claim(sessions, users[role].id)
            async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
                await process_job(job, sessions, settings, saver)
            elapsed = time.monotonic() - started
            result = base.checked(await client.get('/api/v1/messages/' + sent['messageId']), 200)
            files = []
            for deliverable in result.get('deliverables', []):
                for file in deliverable.get('files', []):
                    downloaded = await client.get(file['url'])
                    row = {'name': file['name'], 'bytes': len(downloaded.content), 'status': downloaded.status_code}
                    if file['name'].lower().endswith('.xlsx') and downloaded.status_code == 200:
                        import io
                        import openpyxl
                        book = openpyxl.load_workbook(io.BytesIO(downloaded.content), data_only=True)
                        row['sheets'] = {sheet.title: [list(row) for row in sheet.values] for sheet in book}
                        book.close()
                    files.append(row)
            async with sessions() as db:
                live = await db.get(Job, job.id)
                usages = list((await db.scalars(select(ModelUsage).where(ModelUsage.job_id == job.id))).all())
                works = list((await db.scalars(select(WorkItem).where(WorkItem.owner_id == users[role].id, WorkItem.deleted.is_(False)))).all())
                budget = live.result.get('taskBudget')
                nodes = live.result.get('nodeExecution', {}).get('nodes', [])
            timings = [row for row in trace.rows if row['job'] == job.id]
            first = next((row for row in timings if row['event'] == 'model.first_candidate'), None)
            public = json.dumps(result, ensure_ascii=False)
            checks = {'answered': bool(result.get('reply')), 'terminal': result['job']['state'] in ('succeeded', 'awaiting_input'),
                      'internalBudgetHidden': 'taskBudget' not in public and 'toolReservations' not in public and '内部执行信息' not in public}
            if identifier == 'chat': checks['noTools'] = not any(n['kind'] == 'tool' for n in nodes)
            if identifier == 'research': checks['hasSources'] = bool(live.result.get('webSources'))
            if identifier == 'business': checks['oneWorkCreated'] = len(works) == 1 and works[0].title == '客户访谈准备'
            if identifier == 'file': checks['downloadableXlsx'] = any(f['name'].endswith('.xlsx') and f['status'] == 200 for f in files)
            return {'case': identifier, 'role': role, 'prompt': prompt, 'model': configs['assistant']['model']['model'],
                    'effort': args.effort, 'status': 'PASS' if all(checks.values()) else 'FAIL', 'checks': checks,
                    'seconds': round(elapsed, 3), 'firstCandidateSeconds': round((first['at_unix_ms'] - epoch) / 1000, 3) if first else None,
                    'modelRequests': len(usages), 'tools': sum(n['kind'] == 'tool' for n in nodes), 'workerSql': sql[0],
                    'budget': budget, 'job': result['job'], 'reply': result.get('reply'), 'files': files,
                    'usage': [{'purpose': u.kind, 'status': u.status, 'ms': u.elapsed_ms} for u in usages],
                    'timings': timings}
        finally:
            event.remove(engine.sync_engine, 'before_cursor_execute', statement)
            log.removeHandler(trace)
            await anext(fixture, None)


async def main():
    url = os.getenv('DATABASE_TEST_URL', '')
    if not url or make_url(url).database != 'paa_company_test':
        raise RuntimeError('Dedicated paa_company_test is required')
    if args.output.exists():
        raise RuntimeError('Use a fresh output file; automatic reruns are not supported')
    configs = await base.configuration(args.source_user)
    if args.effort:
        configs['assistant']['choice']['parameters'] = {**configs['assistant']['choice'].get('parameters', {}), 'reasoning_effort': args.effort}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for identifier in args.ids.split(','):
        try:
            row = await evaluate(identifier, configs)
        except Exception as error:
            row = {'case': identifier, 'status': 'ERROR', 'errorType': type(error).__name__}
        with args.output.open('a') as output:
            output.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
        print(json.dumps({key: row.get(key) for key in ('case', 'status', 'seconds', 'firstCandidateSeconds', 'modelRequests', 'tools')}, ensure_ascii=False), flush=True)


asyncio.run(main())
