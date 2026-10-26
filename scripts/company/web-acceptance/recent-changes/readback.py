"""Read-only owned schema evidence. Secrets/authentication tables are excluded."""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from environment import load_environment
from sqlalchemy import create_engine, inspect, text
p=argparse.ArgumentParser();p.add_argument('--metadata',required=True);p.add_argument('--output',required=True);a=p.parse_args()
m,v=load_environment(a.metadata)
if m['suite']!='spec080':raise RuntimeError('Wrong suite')
engine=create_engine(v['environment']['DATABASE_URL'])
allowed=('company_work','company_report','company_job','company_business_action','company_deliverable','company_sandbox_execution','company_message','company_attachment','company_document','company_assistant_interaction','company_model_usage')
out={'schema':m['schema'],'commit':m['commit'],'tables':{}}
with engine.connect() as c:
    c.execute(text('SET TRANSACTION READ ONLY'))
    for name in inspect(c).get_table_names(schema=m['schema']):
        if not name.startswith(allowed):continue
        rows=c.execute(text(f'SELECT * FROM "{m["schema"]}"."{name}"')).mappings().all()
        out['tables'][name]=[{k:v for k,v in r.items() if not any(s in k.lower() for s in ('credential','password','secret','token'))} for r in rows]
with open(a.output,'x') as f:json.dump(out,f,ensure_ascii=False,indent=2,default=str)
print(json.dumps({k:len(v) for k,v in out['tables'].items()}))
