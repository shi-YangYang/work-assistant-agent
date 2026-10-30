"""Explicit real-DB observer probe; owned schema, no provider calls."""
import asyncio,sys,os,json,importlib.util
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
sys.path[:0]=['scripts/benchmarks','scripts/company/web-acceptance','apps/server']
from environment import load_environment
from agent_eval.evidence import write
from agent_eval.facts import commit_coverage,mutations
async def main():
 import argparse
 parser=argparse.ArgumentParser();parser.add_argument('--metadata',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
 source=Path(args.metadata).parent
 _,private=load_environment(source/'metadata.json');os.environ.update(private['environment'])
 state=json.loads((source/'credentials.json').read_text());actor=state['users']['employee']
 out=Path(args.output);out.mkdir(parents=True)
 spec=importlib.util.spec_from_file_location('eval_capture_trace', 'scripts/company/web-acceptance/agent-audit/trace.py');trace=importlib.util.module_from_spec(spec);spec.loader.exec_module(trace);trace.install(out/'trace.jsonl')
 from app.core.config import Settings
 from app.db.session import database
 from app.db import registry
 from app.modules.work.models import WorkItem,WorkRevision
 from app.modules.operations.models import BusinessAction
 from sqlalchemy import text
 engine,sessions=database(Settings());job=SimpleNamespace(id=str(uuid4()),company_id=actor['companyId'],owner_id=actor['id'],attempt=0,fence=1,kind='controlled-contract')
 async def operation(job):
  async with sessions.begin() as db:
   work=WorkItem(company_id=actor['companyId'],owner_id=actor['id'],title='capture fixture',content={'title':'capture fixture','status':'in_progress'})
   db.add(work);await db.flush()
   db.add(WorkRevision(company_id=actor['companyId'],owner_id=actor['id'],work_id=work.id,revision=1,content=work.content,source_ids=[]))
   db.add(BusinessAction(company_id=actor['companyId'],owner_id=actor['id'],message_id=str(uuid4()),step=1,action='create_work',digest='capture',intent_key='capture',state='succeeded',result={'objectType':'work','objectId':work.id,'revision':1,'changedFields':['title','status']}))
  async with sessions() as db:
   saved=await db.get(WorkItem,work.id)
   return {'status':200,'items':[{'id':saved.id,'content':saved.content,'revision':saved.revision}]}
 after=await trace.observe_job(operation)(job)
 events=[json.loads(l) for l in (out/'trace.jsonl').read_text().splitlines()]
 result={'before':{'work':{'status':200,'items':[]}},'turns':[{'receipt':{'jobId':job.id},'readback':{'work':after}}],'trace':events}
 case={'input':{'mutationBounds':[{'workCreate':1,'workUpdate':0,'workDelete':0}],'allowedFields':[{'work':['title','status']}]}}
 rows=mutations(case,result,0,'work','work');assert commit_coverage(result,job.id),events;assert all(r['status']=='PASS' for r in rows),rows
 broken=json.loads(json.dumps(result));broken['trace']=[e for e in broken['trace'] if e['kind']!='database_commit'];assert not commit_coverage(broken,job.id)
 job.id=str(uuid4())
 async def bulk(job):
  async with sessions.begin() as db:
   await db.execute(text('UPDATE company_work_item SET revision=revision+1 WHERE id=:id'),{'id':after['items'][0]['id']})
 await trace.observe_job(bulk)(job)
 all_events=[json.loads(l) for l in (out/'trace.jsonl').read_text().splitlines()]
 assert not commit_coverage({'trace':all_events},job.id)
 write(out/'result.json',{'execution':'controlled-real-database-no-model','assertions':rows,'missing-commit-rejected':True,'unobserved-bulk-write-incomplete':True,'result':result})
 await engine.dispose()
if __name__ == '__main__':
 asyncio.run(main())
