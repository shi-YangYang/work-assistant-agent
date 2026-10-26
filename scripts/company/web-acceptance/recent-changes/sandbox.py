"""Start only this run's nested Docker sandbox; no host daemon configuration changes."""
import json,os,secrets,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from environment import load_environment
m,v=load_environment('artifacts/recent-changes-regression/private/environment.json')
project='spec080-'+m['runId'][:12]
token=secrets.token_hex(32)
env={**os.environ,'LOCAL_SANDBOX_PROJECT':project,'PAA_SANDBOX_TOKEN':token,'PAA_SANDBOX_LOCAL_PORT':'8028'}
base=['docker','compose','-p',project,'-f','deploy/company/compose.sandbox-local.yml']
for kind,source in [('runtime','noria-sandbox-7b87a5efb0-runtime:dev'),('control','spec080-control:ade2d90'),('runner','spec080-runner:ade2d90')]:
 subprocess.run(['docker','tag',source,project+'-'+kind+':dev'],check=True)
subprocess.run(base+['up','-d','--wait','--no-build','runtime'],env=env,check=True)
p1=subprocess.Popen(['docker','save',project+'-runner:dev'],stdout=subprocess.PIPE)
p2=subprocess.run(base+['exec','-T','runtime','docker','load'],env=env,stdin=p1.stdout,check=True);p1.stdout.close();assert p1.wait()==0
subprocess.run(base+['up','-d','--no-build','control'],env=env,check=True)
v['environment'].update(PAA_SANDBOX_URL='http://127.0.0.1:8028',PAA_SANDBOX_TOKEN=token)
Path(m['secretFile']).write_text(json.dumps(v,ensure_ascii=False,indent=2))
public={'project':project,'control':'http://127.0.0.1:8028','runtimeSource':'noria-sandbox-7b87a5efb0-runtime:dev','runnerImage':project+'-runner:dev','controlImage':project+'-control:dev','ownership':'dedicated compose project and volumes','cleanup':['docker','compose','-p',project,'-f','deploy/company/compose.sandbox-local.yml','down','-v']}
Path('artifacts/recent-changes-regression/images/sandbox-ownership.json').write_text(json.dumps(public,indent=2))
