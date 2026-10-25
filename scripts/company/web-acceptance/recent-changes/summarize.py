"""Derive reproducible indexes from immutable attempt evidence, without inference of PASS."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root',default='artifacts/recent-changes-regression');a=p.parse_args()
r=Path(a.root)
def readlines(p):return [json.loads(l) for l in p.read_text().splitlines() if l]
def save(name,value):(r/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str)+'\n')
events=sorted([e for p in r.glob('trace*.jsonl') for e in readlines(p)],key=lambda e:e['time'])
byjob=defaultdict(list)
for e in events:
 if e.get('jobId'):byjob[e['jobId']].append(e)
network=[dict(e,evidence=str(p.relative_to(r))) for p in r.glob('cases/*/network.jsonl') for e in readlines(p)]
receipts=[e for e in network if e['method']=='POST' and e['path']=='/api/v1/messages' and e['status']==202]
assert len(receipts)<=24
save('message-ledger.json',{'limit':24,'acceptedMessageRequests':len(receipts),'requests':receipts,'otherMutationRequests':[e for e in network if e['method']!='GET' and e['path']!='/api/v1/messages'],'note':'Question answer and action confirmation continuations are listed separately, not hidden extra initial prompts.'})
attempts=[]
for p in r.glob('cases/*/journal.jsonl'):
 for row in readlines(p):
  if row['command']['op']!='send':continue
  msg=row.get('result',{}).get('message',{});job=msg.get('job',{});samples=row.get('result',{}).get('samples',[])
  first=next((s['time']-row['started'] for s in samples if s.get('reply',0)>0),None)
  attempts.append({'case':row['command']['case'],'effort':row['command']['effort'],'evidence':str(p.relative_to(r)),'index':row['index'],'durationMs':row['finished']-row['started'],'firstObservedReplyMs':first,'messageId':msg.get('id'),'jobId':job.get('id'),'state':job.get('state'),'error':row.get('error'),'timeout':row.get('result',{}).get('timeout',False),'note':'Child jobs independently checked in readback-final.json; message success does not imply report saved.'})
save('attempt-summary.json',attempts)
summary=[]
for job,items in byjob.items():
 sequence=[]
 for e in items:
  if e['kind'] in ('model_attempt_start','model_attempt_result','model_attempt_error','spec080_provider_input','provider_request_end','tool_dispatch','tool_attempt_result','tool_attempt_error','work_change_plan_input'):
   sequence.append({k:v for k,v in e.items() if k not in ('messages','response','body','transportInput')})
 summary.append({'jobId':job,'start':items[0]['time'],'end':items[-1]['time'],'seconds':items[-1]['time']-items[0]['time'],'counts':dict(Counter(e['kind'] for e in items)),'sequence':sequence})
save('model-tool-ledger.json',{'jobs':summary,'counts':dict(Counter(e['kind'] for e in events)),'limitations':['Initial trace omitted system/developer text; retains their hashes.','Later trace includes actual system/developer text. Exact full tool schemas were not captured during this run; only offered names. Final observer supports schemas for future runs, without rerunning first attempts.','No comparable same-input baseline; no general performance claim.']})
files=[]
for f in r.rglob('*'):
 if not f.is_file() or f.name=='evidence-index.json':continue
 private='private' in f.parts or f.name in ('credentials.json','environment.json','pre-retirement.sql')
 files.append({'path':str(f.relative_to(r)),'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'private':private})
save('evidence-index.json',{'files':files,'warning':'Never publish files marked private; environment files contain paths to secrets, credentials contain passwords, SQL includes account hashes.'})
print(json.dumps({'messages':len(receipts),'attempts':len(attempts),'jobs':len(summary),'evidenceFiles':len(files)}))
