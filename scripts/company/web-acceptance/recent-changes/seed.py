"""Synthetic historical inputs only; generation still enters via Web/scheduler."""
import asyncio,json,os,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from environment import load_environment
m,v=load_environment('artifacts/recent-changes-regression/private/environment.json');os.environ.update(v['environment'])
from app.core.config import Settings
from app.db import registry
from app.db.session import database
from app.modules.work.models import WorkItem,WorkRevision
from app.modules.reports.models import ReportObligation
from sqlalchemy import select

def body(s):return {'schemaVersion':1,'content':[{'type':'paragraph','content':[{'type':'text','text':s}]}]}
async def main():
 engine,sessions=database(Settings());now=datetime.now(timezone.utc);start=(now+timedelta(hours=8)).date()-timedelta(days=(now+timedelta(hours=8)).weekday());rows=[]
 async with sessions.begin() as db:
  for role,offset in [('employee',-7),('peer',0),('realEmployee',0)]:
   account=m['accounts'][role];day=start+timedelta(days=offset);instant=datetime.combine(day,datetime.min.time(),timezone.utc)+timedelta(hours=4)
   for index in range(2):
    content={'title':'同名归档测试','status':'in_progress','body':body('目录已核对；扫描待完成；尚未发送客户。' if index==0 else '已收齐7个议题；会议室尚未确认。'),'summary':'','blocker':'','nextStep':''}
    work=WorkItem(company_id=account['companyId'],owner_id=account['id'],title=content['title'],content=content,created_at=instant,updated_at=instant)
    db.add(work);await db.flush();db.add(WorkRevision(company_id=work.company_id,owner_id=work.owner_id,work_id=work.id,revision=1,content=content,source_ids=[],created_at=instant));rows.append({'role':role,'id':work.id,'period':day.isoformat()})
   if role in ('employee','peer'):
    due=now-timedelta(minutes=1) if role=='peer' else now+timedelta(days=1)
    obligation=ReportObligation(company_id=account['companyId'],owner_id=account['id'],kind='weekly',period=day.isoformat(),period_end=(day+timedelta(days=6)).isoformat(),timezone='Asia/Shanghai',rule_revision=1,generate_at=due,deadline_at=now+timedelta(days=2),reminders=True,before_minutes=30,generation_checked=False)
    db.add(obligation);await db.flush();rows.append({'role':role,'obligationId':obligation.id,'trigger':'real scheduler' if role=='peer' else 'browser obligation'})
 await engine.dispose();Path('artifacts/recent-changes-regression/fixtures/history.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
asyncio.run(main())
