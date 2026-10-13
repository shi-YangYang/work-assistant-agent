"""Bounded independent-account HTTP admission/load in an owned model-free runtime."""
import argparse
import asyncio
import json
import math
import os
from pathlib import Path
import socket
import statistics
import subprocess
import sys
import time
from uuid import uuid4

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from environment import ROOT, load_environment


def distribution(values):
    ordered = sorted(values)
    return {'p50Ms': round(statistics.median(ordered), 2), 'p95Ms': round(ordered[math.ceil(len(ordered) * .95) - 1], 2), 'maxMs': round(max(ordered), 2)} if values else None


async def main(args):
    import httpx
    from sqlalchemy import func, select
    metadata, private = load_environment(args.metadata)
    if metadata['suite'] != 'spec068' or metadata['purpose'] != 'baseline':
        raise RuntimeError('Exact owned Spec068 environment required')
    output = Path(args.output)
    if output.exists():
        raise RuntimeError('First load evidence is immutable')
    os.environ.update(private['environment'])
    from app.core.config import Settings
    from app.db.session import database
    from app.db import registry
    from app.modules.members.models import Member
    from app.modules.work.models import WorkItem
    from app.tasks.models import Job
    settings = Settings()
    engine, sessions = database(settings)
    actors = []
    async with sessions.begin() as db:
        original = await db.get(Member, private['accounts']['employee']['id'])
        for number in range(50):
            actor = Member(company_id=original.company_id, username='s068load_' + uuid4().hex[:16], name='合成并发用户'+str(number), role='employee', password_hash=original.password_hash)
            db.add(actor)
            await db.flush()
            actors.append({'id': actor.id, 'username': actor.username})
    port = int(metadata['apiOrigin'].rsplit(':', 1)[1])
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
    env = {key: value for key, value in os.environ.items() if key.lower() not in ('http_proxy', 'https_proxy', 'all_proxy')}
    log = output.with_suffix('.api.log').open('w')
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)], env=env, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    result = {'schema': metadata['schema'], 'commit': metadata['commit'], 'mode': 'real HTTP API+DB; no worker or model; queued messages are cancelled by owner', 'predeclaredLevels': [1, 5, 10, 30, 50], 'timeoutPerLevel': 60, 'machineLogicalCpus': os.cpu_count(), 'levels': []}
    try:
        async with httpx.AsyncClient(base_url=metadata['apiOrigin'], timeout=2, trust_env=False) as health:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError('Owned load API failed startup')
                try:
                    if (await health.get('/api/v1/health')).status_code == 200:
                        break
                except httpx.ConnectError:
                    pass
                await asyncio.sleep(.1)
            else:
                raise RuntimeError('Owned load API startup deadline')
        for level in result['predeclaredLevels']:
            rows, errors, ids = [], [], []
            started = time.monotonic()
            async def user(index):
                actor = actors[index]
                async with httpx.AsyncClient(base_url=metadata['apiOrigin'], headers={'Origin': metadata['origin']}, timeout=20, trust_env=False) as client:
                    async def request(method, path, expected, **kwargs):
                        began = time.monotonic()
                        response = await client.request(method, path, **kwargs)
                        rows.append({'user': index, 'operation': method+' '+path.split('/jobs/')[0], 'status': response.status_code, 'ms': (time.monotonic()-began)*1000})
                        if response.status_code not in expected:
                            raise RuntimeError(f'{method} {path} unexpected HTTP {response.status_code}')
                        return response.json()
                    try:
                        login = await request('POST','/api/v1/auth/login',{200},json={'username': actor['username'], 'password': private['accounts']['employee']['password']})
                        client.headers['X-CSRF-Token'] = login['csrf']
                        await request('GET','/api/v1/work-items',{200})
                        title=f'并发级别{level}-独立用户{index}'
                        work=await request('POST','/api/v1/work-items',{201},json={'title':title,'summary':'有界合成写入'},headers={'Idempotency-Key':str(uuid4())})
                        assert work['title']==title and work['ownerId']==actor['id']
                        msg=await request('POST','/api/v1/messages',{202},json={'text':f'合成排队取消-{level}-{index}','newConversation':True},headers={'Idempotency-Key':str(uuid4())})
                        cancel=await request('POST','/api/v1/jobs/'+msg['jobId']+'/cancel',{200},json={'expectedAttempt':0,'expectedFence':0})
                        assert cancel['state']=='cancelled'
                        ids.append(msg['jobId'])
                    except Exception as error:
                        errors.append({'user':index,'type':type(error).__name__,'detail':str(error)[:250]})
            try:
                async with asyncio.timeout(60):
                    await asyncio.gather(*(user(index) for index in range(level)))
            except TimeoutError:
                errors.append({'type':'TimeoutError','detail':'Predeclared 60-second level deadline'})
            async with sessions() as db:
                works = await db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.owner_id.in_([a['id'] for a in actors]),WorkItem.title.like(f'并发级别{level}-%')))
                states = dict((await db.execute(select(Job.state,func.count()).where(Job.id.in_(ids)).group_by(Job.state))).all()) if ids else {}
            usage=subprocess.check_output(['ps','-o','%cpu=,rss=','-p',str(process.pid)],text=True).split()
            row={'concurrency':level,'seconds':round(time.monotonic()-started,3),'requests':len(rows),'errors':errors,'errorRate':len(errors)/level,'latency':distribution([r['ms'] for r in rows]),'loginLatency':distribution([r['ms'] for r in rows if r['operation']=='POST /api/v1/auth/login']),'worksPersisted':works,'jobStates':states,'apiCpuPercent':float(usage[0]),'apiRssBytes':int(usage[1])*1024,'inspectorPoolCheckedOutAfter':engine.pool.checkedout(),'requestObservations':rows}
            row['status']='PASS' if not errors and works==level and states=={'cancelled':level} else 'FAIL'
            result['levels'].append(row)
            output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
            if row['status']=='FAIL' or row['apiRssBytes']>600*1024*1024:
                result['stoppedEscalation']=True
                break
    finally:
        process.terminate()
        try: process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=5)
        log.close()
        result['ownedApiStopped']=process.poll() is not None
        result['inspectorPoolCheckedOutAfter']=engine.pool.checkedout()
        output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
        await engine.dispose()
    print(json.dumps({'levels':[{k:r[k] for k in ('concurrency','seconds','status','latency')} for r in result['levels']]}),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata',required=True)
    parser.add_argument('--output',required=True)
    asyncio.run(main(parser.parse_args()))
