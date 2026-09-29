"""Opt-in synthetic real-model journeys through a running isolated API/worker.

No direct processing or database mutations; credentials are never emitted. First
responses and read-back evidence are append-only. A completed job is not a
semantic PASS: each case remains review-required until its objective is checked.
"""
import argparse, asyncio, json, os, time
from pathlib import Path
from uuid import uuid4
import httpx

TERMINAL={'succeeded','failed','cancelled','awaiting_retry','awaiting_input'}

async def read_pages(client, path, **params):
 items=[];cursor=None
 while True:
  response=await client.get(path,params={**params,'limit':20,**({'cursor':cursor} if cursor else {})})
  if response.status_code!=200:return {'status':response.status_code,'body':response.json()}
  data=response.json();items.extend(data['items'])
  cursor=data.get('nextCursor')
  if not cursor:return {'status':200,'body':{'items':items,'nextCursor':None}}

async def main():
 parser=argparse.ArgumentParser();parser.add_argument('--state',required=True);parser.add_argument('--cases',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
 secret=Path(args.state)
 if secret.stat().st_mode & 0o077: raise RuntimeError('Private credentials required')
 state=json.loads(secret.read_text());cases=json.loads(Path(args.cases).read_text())
 if not state['schema'].startswith('spec044_web_') or state['apiOrigin']!='http://127.0.0.1:8016':raise RuntimeError('Local isolated acceptance only')
 out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
 records=out/'first.jsonl'
 if records.exists():raise RuntimeError('Refusing to overwrite first results')
 count=0
 for case in cases:
  role=case.get('role','realApiEmployee');user=state['users'][role]
  async with httpx.AsyncClient(base_url=state['apiOrigin'],headers={'Origin':state['origin']},timeout=30) as c:
   response=await c.post('/api/v1/auth/login',json={'username':user['username'],'password':user['password']});response.raise_for_status();c.headers['X-CSRF-Token']=response.json()['csrf']
   conversation=None;rows=[]
   for index,prompt in enumerate(case['turns']):
    count+=1
    if count>100:raise RuntimeError('HTTP message budget exhausted')
    started=time.monotonic();body={'text':prompt,'attachmentIds':[],**({'conversationId':conversation} if conversation else {'newConversation':True,'personaId':case.get('persona','professional'),'executionMode':case.get('mode','full'),'fullAccessConfirmed':True})}
    if index==0:
     for filename in case.get('attachments',[]):
      p=Path(filename)
      with p.open('rb') as f:
       upload=await c.post('/api/v1/uploads',files={'file':(p.name,f)})
      upload.raise_for_status();body['attachmentIds'].append(upload.json()['id'])
    try:
     sent=await c.post('/api/v1/messages',json=body,headers={'Idempotency-Key':str(uuid4())});sent.raise_for_status();receipt=sent.json();conversation=receipt['conversationId']
     if case.get('cancelFirst') and index==0:
      await asyncio.sleep(1)
      job=(await c.get('/api/v1/jobs/'+receipt['jobId'])).json()
      cancel=await c.post('/api/v1/jobs/'+receipt['jobId']+'/cancel',json={'expectedAttempt':job['attempt'],'expectedFence':job['fence']});cancel.raise_for_status()
     async with asyncio.timeout(300):
      while True:
       value=(await c.get('/api/v1/messages/'+receipt['messageId'])).json()
       if value.get('job',{}).get('state') in TERMINAL:break
       await asyncio.sleep(1)
     files=[]
     for result in value.get('deliverables',[]):
      for file in result.get('files',[]):
       url=file['url']
       if not url.startswith('/api/v1/'):raise RuntimeError('Unexpected generated download URL')
       data=await c.get(url); data.raise_for_status()
       name=Path(file['name']).name; dest=out/'files'/case['id']/str(index);dest.mkdir(parents=True,exist_ok=True);(dest/name).write_bytes(data.content)
       files.append({'name':name,'size':len(data.content),'declaredSize':file['size'],'path':str(dest/name)})
     row={'case':case['id'],'turn':index+1,'prompt':prompt,'receipt':receipt,'message':value,'files':files,'seconds':round(time.monotonic()-started,2),'classification':'review-required'}
    except Exception as e:
     row={'case':case['id'],'turn':index+1,'prompt':prompt,'exception':type(e).__name__,'detail':str(e)[:300],'seconds':round(time.monotonic()-started,2),'classification':'incomplete'}
    with records.open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    print(json.dumps({'case':case['id'],'turn':index+1,'state':row.get('message',{}).get('job',{}).get('state'),'error':row.get('exception'),'seconds':row['seconds']},ensure_ascii=False),flush=True)
    rows.append(row)
    if 'exception' in row:break
   evidence={}
   for label,path in {'work':'/api/v1/work-items','reports':'/api/v1/reports'}.items():
    evidence[label]=await read_pages(c,path,**({'kind':'weekly'} if label=='reports' else {}))
   (out/(case['id']+'.json')).write_text(json.dumps({'case':case,'turns':rows,'evidence':evidence},ensure_ascii=False,indent=2))
   await c.post('/api/v1/auth/logout',json={})
 print('Finished synthetic HTTP user messages: '+str(count),flush=True)
if __name__=='__main__':asyncio.run(main())
