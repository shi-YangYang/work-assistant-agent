"""Fixed body/checklist-only report generation and rewrite at low/high effort."""
import argparse
import asyncio
from datetime import datetime
import json
from pathlib import Path
import sys
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/benchmarks/work-checklist'))
from run import checked, database_evidence, load_environment, paragraph, send, setup, trace_evidence, write_json


def evidence(private, report_id):
    engine = create_engine(private['environment']['DATABASE_URL'])
    try:
        with engine.connect() as db:
            db.execute(text('SET TRANSACTION READ ONLY'))
            report = db.execute(text('SELECT id,revision,content,candidate,source_ids,published_revision FROM company_report WHERE id=:id'), {'id': report_id}).mappings().one()
            jobs = db.execute(text("SELECT id,state,error,result FROM company_job WHERE target_id=:id AND kind='report' ORDER BY created_at"), {'id': report_id}).mappings().all()
            usage = db.execute(text('SELECT kind,status,model_name,elapsed_ms,actual_input_tokens,actual_output_tokens FROM company_model_usage WHERE job_id = ANY(:ids) ORDER BY created_at'), {'ids': [row['id'] for row in jobs]}).mappings().all()
            count = db.scalar(text('SELECT count(*) FROM company_work_update WHERE owner_id=:owner'), {'owner': private['accounts']['realEmployee']['id']})
            return {'report': dict(report), 'jobs': [dict(row) for row in jobs], 'modelUsage': [dict(row) for row in usage], 'workUpdateCount': count}
    finally:
        engine.dispose()


async def main(root):
    metadata, private = load_environment(root / 'environment.json')
    if metadata.get('suite') != 'spec079':
        raise RuntimeError('Requires owned spec079 environment')
    directory = root / 'real'
    directory.mkdir()
    date = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    async with httpx.AsyncClient(base_url=metadata['apiUrl'], headers={'Origin': metadata['origin']}, timeout=45, trust_env=False) as client:
        await setup(client, private, 'low')
        fixtures = [
            {'title': '合成档案归整', 'status': 'done', 'body': {'schemaVersion': 1, 'content': [paragraph('今日已将三份项目资料归档并核对索引，归档工作已完成。')]}},
            {'title': '合成周会筹备', 'status': 'in_progress', 'blocker': '会议室尚未确认', 'nextStep': '确认会议室后发送议程',
             'body': {'schemaVersion': 1, 'content': [paragraph('周会筹备尚未完成。'), {'type': 'taskList', 'content': [
                 {'type': 'taskItem', 'attrs': {'checked': True}, 'content': [paragraph('收齐参会者议题')]},
                 {'type': 'taskItem', 'attrs': {'checked': False}, 'content': [paragraph('发送会议议程')]}]}]}},
        ]
        works = [checked(await client.post('/api/v1/work-items', json=item, headers={'Idempotency-Key': str(uuid4())}), (201,)) for item in fixtures]
        write_json(directory / 'fixtures.json', {'works': works, 'date': date, 'sampling': 'one generation and one rewrite per effort, no resampling'})
        for effort in ('low', 'high'):
            target = directory / effort
            target.mkdir()
            reasoning = await setup(client, private, effort)
            generation_dir = target / 'generate'
            generation_dir.mkdir()
            started = time.perf_counter()
            generation = await send(client, {'text': f'请根据我在 {date} 所在周的工作生成周报，保留已完成成果、进行中事项、阻碍和下一步，保存草稿，不要提交。',
                'attachmentIds': [], 'reasoning': reasoning, 'newConversation': True, 'personaId': 'professional'}, generation_dir, timeout=240)
            receipt = generation.get('receipt', {})
            if not receipt:
                write_json(generation_dir / 'result.json', generation)
                break
            generation['database'] = database_evidence(private, receipt['jobId'], receipt['messageId'])
            generation['trace'] = trace_evidence(root / 'trace.jsonl', receipt['jobId'])
            actions = generation.get('message', {}).get('actions', [])
            action = next((row for row in actions if row.get('action') == 'generate_report'), None)
            if not action or not action.get('objectId'):
                write_json(generation_dir / 'result.json', generation)
                print(json.dumps({'effort': effort, 'generation': 'no report receipt'}, ensure_ascii=False), flush=True)
                break
            report_id = action['objectId']
            async with asyncio.timeout(240):
                while True:
                    report = checked(await client.get('/api/v1/reports/' + report_id))
                    if report.get('job', {}).get('state') not in ('queued', 'running'):
                        break
                    await asyncio.sleep(.5)
            generation.update(report=report, reportDatabase=evidence(private, report_id), totalSeconds=time.perf_counter() - started)
            generation['childTrace'] = trace_evidence(root / 'trace.jsonl', report['job']['id'])
            generation['messageAfterReport'] = checked(await client.get('/api/v1/messages/' + receipt['messageId']))
            write_json(generation_dir / 'result.json', generation)
            print(json.dumps({'effort': effort, 'generation': report['job']['state'], 'seconds': generation['totalSeconds'],
                'assistantCalls': generation['trace']['providerRequests'], 'reportCalls': generation['childTrace']['providerRequests'],
                'candidate': bool(report.get('candidate')), 'workUpdates': generation['reportDatabase']['workUpdateCount']}, ensure_ascii=False), flush=True)
            if report['job']['state'] != 'succeeded':
                break
            if report.get('candidate'):
                report = checked(await client.post('/api/v1/reports/' + report_id + '/candidate', json={'expectedRevision': report['revision']}))
                write_json(target / 'adopted.json', report)
            rewrite_dir = target / 'rewrite'
            rewrite_dir.mkdir()
            rewrite = await send(client, {'text': f'请读取周报（ID：{report_id}），将四个栏目的文字精简成简短条目，保留归档成果、收齐议题、尚未发送议程和会议室未确认的事实。直接保存修改，不要提交。',
                'attachmentIds': [], 'reasoning': reasoning, 'conversationId': receipt['conversationId']}, rewrite_dir, timeout=240)
            if rewrite.get('receipt'):
                ids = rewrite['receipt']
                rewrite['database'] = database_evidence(private, ids['jobId'], ids['messageId'])
                rewrite['trace'] = trace_evidence(root / 'trace.jsonl', ids['jobId'])
            rewrite['report'] = checked(await client.get('/api/v1/reports/' + report_id))
            rewrite['reportDatabase'] = evidence(private, report_id)
            write_json(rewrite_dir / 'result.json', rewrite)
            print(json.dumps({'effort': effort, 'rewrite': rewrite.get('message', {}).get('job', {}).get('taskOutcome'),
                'seconds': rewrite['metrics'].get('finalReadbackSeconds'), 'calls': rewrite.get('trace', {}).get('providerRequests')}, ensure_ascii=False), flush=True)
        await client.post('/api/v1/auth/logout', json={})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', required=True)
    asyncio.run(main(Path(parser.parse_args().evidence).resolve()))
