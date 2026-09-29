"""Opt-in real-model, real-sandbox task evaluation in a disposable DB schema.

Only model configuration is read from the local source account. No messages are
sent to that account. Requires an isolated local sandbox test service; do not run
alongside the normal server test suite. Results contain synthetic task data only.
"""
import argparse
import asyncio
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from uuid import uuid4
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'apps/server'), str(ROOT / 'tests/server'), str(Path(__file__).parent)]
from dotenv import dotenv_values
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from app.tasks.handlers import process_job
from app.tasks.queue import claim
from app.modules.work.models import WorkItem
from app.modules.deliverables.models import DeliverableRevision
from app.modules.executions.models import SandboxExecution
from app.tasks.models import Job
from conftest import setup

loader = importlib.util.spec_from_file_location('agent_evaluation', ROOT / 'scripts/benchmarks/agent-evaluation.py')
evaluation = importlib.util.module_from_spec(loader)
loader.loader.exec_module(evaluation)


async def turn(fixture, saver, prompt, conversation=None, attachments=None, who='employee'):
    settings, sessions, users, clients = fixture
    body = {'text': prompt, 'attachmentIds': attachments or [], 'personaId': 'professional'}
    body.update({'conversationId': conversation} if conversation else {'newConversation': True})
    sent = evaluation.checked(await clients[who].post('/api/v1/messages', json=body, headers={'Idempotency-Key': str(uuid4())}), 202)
    started = time.monotonic()
    for _ in range(12):
        job = await claim(sessions, users[who].id)
        if job is None:
            break
        async with asyncio.timeout(460):
            await process_job(job, sessions, settings, saver)
    value = evaluation.checked(await clients[who].get('/api/v1/messages/' + sent['messageId']), 200)
    files = []
    for result in value.get('deliverables', []):
        for file in result.get('files', []):
            response = await clients[who].get(file['url'])
            if response.status_code != 200:
                raise AssertionError('Generated file download failed: ' + str(response.status_code))
            if len(response.content) != file['size']:
                raise AssertionError('Generated file size mismatch')
            saved = ROOT / 'artifacts/spec042/real-model-files' / sent['messageId']
            saved.mkdir(parents=True, exist_ok=True)
            if Path(file['name']).name != file['name']:
                raise AssertionError('Unsafe download name')
            (saved / file['name']).write_bytes(response.content)
            suffix = Path(file['name']).suffix.lower()
            details = {'name': file['name'], 'size': file['size'], 'revision': result['revision'], 'id': result['id']}
            if suffix in ('.docx', '.pptx', '.xlsx'):
                with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                    details['entries'] = len(archive.namelist())
                    if suffix == '.pptx':
                        slides = [name for name in archive.namelist() if name.startswith('ppt/slides/slide') and name.endswith('.xml')]
                        details['slides'] = len(slides)
                    if suffix == '.xlsx':
                        import openpyxl
                        workbook = openpyxl.load_workbook(io.BytesIO(response.content), data_only=True)
                        details['sheets'] = {sheet.title: [list(row) for row in sheet.iter_rows(values_only=True)][:24] for sheet in workbook}
                        workbook.close()
            elif suffix in ('.txt', '.md', '.csv', '.json'):
                details['text'] = response.content.decode('utf-8-sig')[:4000]
            files.append(details)
    async with sessions() as db:
        executions = list((await db.scalars(select(SandboxExecution).where(SandboxExecution.message_id == sent['messageId']))).all())
        job = await db.get(Job, sent['jobId'])
        nodes = [{'label': n.get('label'), 'state': n.get('state')} for n in job.result.get('nodeExecution', {}).get('nodes', [])]
        actual_work = list((await db.scalars(select(WorkItem).where(WorkItem.owner_id == users[who].id, WorkItem.deleted.is_(False)))).all())
    return {'prompt': prompt, 'conversation': sent['conversationId'], 'messageId': sent['messageId'],
            'state': value.get('job', {}).get('state'), 'outcome': value.get('job', {}).get('taskOutcome'), 'reply': value.get('reply'), 'error': value.get('job', {}).get('error'),
            'seconds': round(time.monotonic() - started, 2), 'files': files, 'nodes': nodes,
            'executions': [{'state': row.state, 'stdout': row.result.get('stdout'), 'stderr': row.result.get('stderr')} for row in executions],
            'workTitles': [row.title for row in actual_work]}


def spreadsheet_total(files, expected):
    for file in files:
        for title, rows in file.get('sheets', {}).items():
            for row in rows:
                if any(any(label in str(cell).lower() for label in ('合计', '总额', '总金额', '总计', '净销售', 'total', 'net')) for cell in row):
                    if any(isinstance(cell, (int, float)) and abs(cell - expected) < .001 for cell in row):
                        return True
    return False


async def evaluate(configs, output, *, office_only=False):
    with tempfile.TemporaryDirectory(prefix='noria-sandbox-eval-') as directory:
        fixture_generator = setup.__wrapped__(Path(directory))
        fixture = await anext(fixture_generator)
        settings, sessions, users, clients = fixture
        report = []
        def record(name, data, checks):
            row = {'case': name, **data, 'checks': checks, 'pass': all(checks.values())}
            output.write(json.dumps(row, ensure_ascii=False, default=str) + '\n'); output.flush()
            report.append(row)
            print(name + ': ' + ('PASS' if row['pass'] else 'FAIL'), flush=True)
        try:
            await evaluation.install_models(configs, settings, sessions, users['employee'].company_id)
            async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
                if office_only:
                    row = await turn(fixture, saver, '请生成“诺亚发布计划”的两页可编辑中文 PPTX，同时生成包含同样内容的 Word DOCX 和 PDF 文件。内容：第一页目标为10月试运行，第二页列出测试、培训、收集反馈三个步骤。不要加入我的工作。')
                    record('office-portable-fonts', row, {'succeeded': row['state'] == 'succeeded', 'pptx': any(f['name'].endswith('.pptx') and f.get('slides') == 2 for f in row['files']), 'docx': any(f['name'].endswith('.docx') for f in row['files']), 'pdf': any(f['name'].endswith('.pdf') for f in row['files'])})
                    return report
                for index, prompt in enumerate(['请用两句话解释光合作用。', '把“今天下午三点开会”翻译成英文，只给翻译。', '解释 Python 的列表推导式，并举一个小例子；不用实际运行。']):
                    row = await turn(fixture, saver, prompt)
                    record('ordinary-' + str(index), row, {'answered': bool(row['reply']) and row['outcome']['state'] == 'completed', 'noExecution': not row['executions'], 'noBusinessWrite': not row['workTitles']})
                uploaded = evaluation.checked(await clients['employee'].post('/api/v1/uploads', files={'file': ('sales.csv', '客户,金额,退款\n甲,120,false\n甲,120,false\n乙,80,true\n丙,,false\n'.encode(), 'text/csv')}), 201)
                row = await turn(fixture, saver, '分析附件，去掉完全重复行，金额空值不计入合计，排除退款；告诉我净销售额，生成包含清洗数据和合计的 Excel 以及柱状图 PNG。不要记录工作。', attachments=[uploaded['id']])
                conversation = row['conversation']
                record('uploaded-data-analysis', row, {'succeeded': row['state'] == 'succeeded', 'knownNetInXlsx': spreadsheet_total(row['files'], 120), 'xlsx': any(f['name'].endswith('.xlsx') for f in row['files']), 'png': any(f['name'].endswith('.png') for f in row['files']), 'noBusinessWrite': not row['workTitles']})
                row = await turn(fixture, saver, '现在把退款也纳入统计，仍去重并忽略空金额。更新刚才的 Excel 文件，保留上一版。', conversation=conversation)
                record('continued-file-version', row, {'succeeded': row['state'] == 'succeeded', 'knownTotalInXlsx': spreadsheet_total(row['files'], 200), 'newVersion': any(f['revision'] >= 2 for f in row['files'])})
                row = await turn(fixture, saver, '请生成“诺亚发布计划”的两页可编辑中文 PPTX，同时生成包含同样内容的 Word DOCX 和 PDF 文件。内容：第一页目标为10月试运行，第二页列出测试、培训、收集反馈三个步骤。不要加入我的工作。')
                record('office-presentation', row, {'succeeded': row['state'] == 'succeeded', 'pptx': any(f['name'].endswith('.pptx') and f.get('slides') == 2 for f in row['files']), 'docx': any(f['name'].endswith('.docx') for f in row['files']), 'pdf': any(f['name'].endswith('.pdf') for f in row['files'])})
                row = await turn(fixture, saver, '生成四个真实可下载文件：TXT、Markdown、JSON、CSV。它们都表示下面数据：苹果数量3，单价2；香蕉数量2，单价4。计算总额，并在四个文件里包含总额。不要记录工作。')
                record('text-data-formats', row, {'succeeded': row['state'] == 'succeeded', 'fourFormats': {Path(f['name']).suffix.lower() for f in row['files']} >= {'.txt', '.md', '.json', '.csv'}, 'knownTotal': '14' in str(row['reply']) + str(row['files'])})
                row = await turn(fixture, saver, '联网查一下 Python 官方文档对列表推导式的介绍，写一个简短的中文 Markdown 文件供下载，附官方来源链接，不写入工作。')
                record('web-to-file', row, {'succeeded': row['state'] == 'succeeded', 'fileWithSource': any('python.org' in f.get('text', '') for f in row['files'])})
                row = await turn(fixture, saver, '拟一个三步的软件试运行检查清单，保存为个人方案，暂时不要写我的工作。')
                conversation = row['conversation']
                record('private-plan', row, {'succeeded': row['state'] == 'succeeded', 'noBusinessWrite': not row['workTitles']})
                row = await turn(fixture, saver, '把刚才方案的前两项加入我的工作，保持进行中。', conversation=conversation)
                record('plan-to-business', row, {'succeeded': row['state'] == 'succeeded', 'twoWorks': len(row['workTitles']) == 2})
                async def personal(who, mark):
                    return await turn(fixture, saver, f'生成一个文件名为“结果.txt”的文件，内容只有“{mark}”。不写入工作。', who=who)
                for role, row in zip(('employee', 'peer'), await asyncio.gather(personal('employee', '个人甲'), personal('peer', '个人乙'))):
                    expected = '个人甲' if role == 'employee' else '个人乙'
                    record('parallel-' + role, row, {'succeeded': row['state'] == 'succeeded', 'ownFile': any(f.get('text', '').strip() == expected for f in row['files'])})
        finally:
            await fixture_generator.aclose()
        return report


async def main(args):
    configs = await evaluation.configuration(args.source_user)
    values = dotenv_values(ROOT / 'apps/server/.env.web')
    url = make_url(os.environ.get('DATABASE_TEST_URL') or values['DATABASE_TEST_URL']).set(drivername='postgresql+psycopg')
    if url.database != 'paa_company_test':
        raise RuntimeError('Refusing non-test database')
    private = dotenv_values(ROOT / 'artifacts/spec042/private/control.env')
    if not private.get('SANDBOX_TOKEN'):
        raise RuntimeError('Isolated test control.env missing')
    os.environ['PAA_SANDBOX_URL'] = private['SANDBOX_TEST_URL']
    os.environ['PAA_SANDBOX_TOKEN'] = private['SANDBOX_TOKEN']
    schema = 'sandbox_eval_' + uuid4().hex
    engine = create_engine(url)
    scoped = url.update_query_dict({'options': '-csearch_path=' + schema}).render_as_string(hide_password=False)
    os.environ['DATABASE_URL'] = os.environ['DATABASE_TEST_URL'] = scoped
    os.environ['PYTHONPATH'] = str(ROOT / 'apps/server') + os.pathsep + str(ROOT / 'packages/voiceprint-engine/src')
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with engine.begin() as db: db.execute(CreateSchema(schema))
        with output.with_suffix('.setup.log').open('w') as log:
            subprocess.run([sys.executable, '-m', 'app.cli', 'migrate'], cwd=ROOT, check=True, stdout=log, stderr=subprocess.STDOUT, timeout=90)
        with output.open('w') as stream:
            report = await evaluate(configs, stream, office_only=args.office_only)
        return all(row['pass'] for row in report)
    finally:
        with engine.begin() as db: db.execute(DropSchema(schema, cascade=True))
        engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-user', default='admin')
    parser.add_argument('--office-only', action='store_true')
    parser.add_argument('--output', default='artifacts/spec042/real-model.jsonl')
    raise SystemExit(0 if asyncio.run(main(parser.parse_args())) else 1)
