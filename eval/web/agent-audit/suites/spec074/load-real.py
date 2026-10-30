"""Bounded admission, then real-model completion for independent owned accounts.

Each level admits for at most 60 seconds. Model work continues to its actual
terminal state; answers, tool decisions, and outputs are never synthesized.
"""
import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from uuid import uuid4

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('fault_campaign', HERE / 'fault-campaign.py')
campaign_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(campaign_module)
Campaign = campaign_module.Campaign
runtime = campaign_module.runtime


async def prepare_actors(campaign):
    os.environ.update(campaign.private['environment'])
    from app.core.config import Settings
    from app.db.session import database
    from app.db import registry
    from app.modules.members.models import Member
    from app.modules.model_services.reasoning.settings import read_settings, update_settings
    from app.modules.model_services.reasoning.schemas import UpdateReasoning
    engine, sessions = database(Settings())
    actors = []
    try:
        async with sessions.begin() as db:
            source = await db.get(Member, campaign.private['accounts']['employee']['id'])
            for index in range(50):
                actor = Member(company_id=source.company_id, username='s074_load_'+uuid4().hex[:16],
                    name='合成负载用户'+str(index+1), role='employee', password_hash=source.password_hash)
                db.add(actor)
                await db.flush()
                view = await read_settings(db, actor)
                await update_settings(db, actor, UpdateReasoning(effort='low', preferenceRevision=view['preferenceRevision'], configVersion=view['configVersion']))
                actors.append({'id': actor.id, 'username': actor.username})
    finally:
        await engine.dispose()
    return actors


async def main(args):
    import httpx
    campaign = Campaign(args.output)
    destination = campaign.output / 'load'
    destination.mkdir(exist_ok=True)
    if (destination/'results.json').exists():
        raise RuntimeError('Refusing to overwrite first load evidence')
    actors = await prepare_actors(campaign)
    runtime.save(destination/'actors.json', actors)
    result = {'predeclaredLevels': [1,5,10,30,50], 'admissionDeadlineSeconds': 60,
              'terminalObservationDeadlineSeconds': 1500, 'workerConcurrency': 3,
              'logicalCpus': os.cpu_count(), 'modelMode': 'real upstream low; no provider response fixtures',
              'host': 'local test host; not a production 8-core/16GB capacity claim', 'levels': []}
    for level in result['predeclaredLevels']:
        campaign.case = 'L01-'+str(level)
        rows, clients = [], {}
        start = time.time()
        resource_stop = asyncio.Event()

        async def resources():
            while not resource_stop.is_set():
                samples = {'level': level, 'time': time.time()}
                for service in ('api','worker'):
                    pid = json.loads((campaign.output/(service+'-process.json')).read_text())['pid']
                    proc = await asyncio.create_subprocess_exec('ps','-p',str(pid),'-o','%cpu=,rss=',stdout=asyncio.subprocess.PIPE)
                    out, _ = await proc.communicate()
                    fields = out.decode().split()
                    if len(fields)==2:
                        samples[service] = {'cpuPercent': float(fields[0]), 'rssBytes': int(fields[1])*1024}
                campaign_module.append(destination/'resources.jsonl', samples)
                try:
                    await asyncio.wait_for(resource_stop.wait(), 2)
                except TimeoutError:
                    pass

        monitor = asyncio.create_task(resources())

        async def admit(index):
            began = time.time()
            actor = actors[index]
            row = {'index':index, 'actorId':actor['id'], 'type':['short','document','work'][index%3], 'startedAt':began}
            rows.append(row)
            client = httpx.AsyncClient(base_url=campaign.metadata['apiOrigin'], headers={'Origin':campaign.metadata['origin']}, timeout=45, trust_env=False)
            clients[index] = client
            try:
                login = await client.post('/api/v1/auth/login', json={'username':actor['username'], 'password':campaign.private['accounts']['employee']['password']})
                row['login'] = {'status':login.status_code, 'seconds':round(time.time()-began,3)}
                login.raise_for_status()
                client.headers['X-CSRF-Token'] = login.json()['csrf']
                marker = f'L{level}-U{index}-'+uuid4().hex[:6]
                row['marker'] = marker
                attachment_ids = []
                if index%3 == 1:
                    content = f'本材料编号：{marker}。合同数量{index+17}份，每份{index+23}元。'
                    upload = await client.post('/api/v1/uploads', files={'file':('load-material.txt',content.encode(),'text/plain')})
                    upload.raise_for_status()
                    attachment_ids = [upload.json()['id']]
                    prompt = '根据附件计算合同总金额，并说出材料编号；只需一句话，不要创建业务记录。'
                    row['expectedNumber'] = (index+17)*(index+23)
                elif index%3 == 2:
                    prompt = f'创建一项我的工作，标题“{marker}负载核对”，内容“核对合成材料{index+17}份”，状态进行中。只创建这一项。'
                    row['expectedTitle'] = marker+'负载核对'
                else:
                    prompt = f'计算{index+17}乘以{index+23}，回答时带上本轮编号{marker}。仅用一句话，不查询业务资料。'
                    row['expectedNumber'] = (index+17)*(index+23)
                sent = time.time()
                receipt, _, _ = await campaign.post(client, prompt, attachment_ids=attachment_ids)
                row.update(receipt=receipt, sentAt=sent, acceptedAt=time.time(), admissionSeconds=round(time.time()-sent,3))
                campaign_module.append(destination/'admissions.jsonl', {'level':level, **row})
            except Exception as error:
                row['admissionError'] = {'type':type(error).__name__, 'detail':str(error)[:250]}

        try:
            async with asyncio.timeout(60):
                await asyncio.gather(*(admit(index) for index in range(level)))
        except TimeoutError:
            result['admissionDeadlineReached'] = level

        async def finish(row):
            if not row.get('receipt'):
                return
            try:
                row['terminal'] = await campaign.settle(clients[row['index']], row['receipt'])
                row['totalSeconds'] = round(time.time()-row['sentAt'],3)
                row['trace'] = campaign.summary(row['receipt'])
                row['readback'] = await campaign.snapshot(clients[row['index']])
                message = row['terminal']['message']
                reply = message.get('reply','')
                own = message.get('ownerId') == row['actorId']
                no_cross_marker = all(other.get('marker') not in reply for other in rows if other is not row and other.get('marker'))
                if row['type']=='work':
                    matching = [work for work in row['readback']['work']['body'].get('items',[]) if work['title']==row['expectedTitle']]
                    correct = len(matching)==1 and matching[0]['ownerId']==row['actorId']
                    row['matchingWorkCount'] = len(matching)
                else:
                    correct = row['marker'] in reply and str(row['expectedNumber']) in reply.replace(',','')
                row['assertions'] = {'ownedMessage':own, 'noOtherUserMarker':no_cross_marker,
                                     'expectedFactOrSideEffect':correct,
                                     'realUpstreamObserved':row['trace']['upstreamCalls']>0}
                completed = message['job']['state']=='succeeded' or (message['job']['state']=='awaiting_input'
                    and message['job'].get('taskOutcome',{}).get('state')=='completed' and not message['job'].get('incompleteTask'))
                row['status'] = 'PASS' if completed and all(row['assertions'].values()) else 'FAIL'
            except Exception as error:
                row['terminalError'] = {'type':type(error).__name__, 'detail':str(error)[:250]}
            finally:
                campaign_module.append(destination/'terminals.jsonl', {'level':level, **row})

        await asyncio.gather(*(finish(row) for row in rows))
        resource_stop.set()
        await monitor
        await asyncio.gather(*(client.aclose() for client in clients.values()))
        seconds = [row['totalSeconds'] for row in rows if 'totalSeconds' in row]
        upstream = [status for row in rows for status in row.get('trace',{}).get('upstreamStatuses',[])]
        failed = [row for row in rows if row.get('admissionError') or row.get('terminalError') or row.get('status')!='PASS']
        observed = {'level':level, 'startedAt':start, 'finishedAt':time.time(), 'seconds':round(time.time()-start,3),
                    'accepted':sum('receipt' in row for row in rows), 'failed':len(failed), 'upstreamCalls':len(upstream),
                    'upstreamStatuses':{str(status):upstream.count(status) for status in set(upstream)},
                    'medianSeconds':round(statistics.median(seconds),3) if seconds else None,
                    'rangeSeconds':[min(seconds),max(seconds)] if seconds else None, 'rows':rows, 'status':'PASS' if not failed else 'FAIL'}
        result['levels'].append(observed)
        runtime.save(destination/'results.json',result)
        print(json.dumps({k:observed[k] for k in ('level','seconds','accepted','failed','upstreamCalls','upstreamStatuses','medianSeconds','rangeSeconds')}),flush=True)
        if upstream.count(429)>=2 or len(failed)>=max(2,level*.1):
            result['stoppedEscalation'] = {'level':level,'reason':'Repeated upstream rate limiting or >=10% task failures; preserve first results'}
            runtime.save(destination/'results.json',result)
            break


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    asyncio.run(main(parser.parse_args()))
