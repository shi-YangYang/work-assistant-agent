"""Spec074 owned fault runner; model responses always originate upstream.

The only transport alterations are explicit failures after a real HTTP request.
No fixture supplies an answer, tool call, transcript, image, or document.
"""
import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[5]
BASE = ROOT / 'scripts/company/web-acceptance'
AUDIT = ROOT / 'eval/web/agent-audit'
sys.path[:0] = [str(AUDIT), str(BASE), str(ROOT / 'apps/server')]
from environment import load_environment


def save(path, value):
    path=Path(path)
    temporary=path.with_name(path.name+'.writing')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')
    temporary.chmod(path.stat().st_mode & 0o777 if path.exists() else 0o600)
    temporary.replace(path)


def command(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs).stdout.strip()


def prepare(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / 'environment.json'
    if manifest.exists():
        raise RuntimeError('Refusing to overwrite first environment')
    tag = 'spec074-fault-' + uuid4().hex[:10]
    password = secrets.token_urlsafe(24)
    for port in (55474, 56474, 8024):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', port))
    pg = command('docker', 'run', '-d', '--name', tag+'-pg', '--label', 'noria.audit.owner='+tag,
                 '-p', '127.0.0.1:55474:5432', '-e', 'POSTGRES_USER=paa', '-e', 'POSTGRES_PASSWORD='+password,
                 '-e', 'POSTGRES_DB=paa_company_test', 'postgres:17.11-bookworm')
    redis = command('docker', 'run', '-d', '--name', tag+'-redis', '--label', 'noria.audit.owner='+tag,
                    '-p', '127.0.0.1:56474:6379', 'redis:7.4.2-alpine')
    save(output / 'ownership.json', {'tag': tag, 'postgres': pg, 'redis': redis,
         'ports': {'postgres': 55474, 'redis': 56474, 'api': 8024}, 'createdAt': time.time(),
         'dailyContainers': command('docker', 'ps', '--format', '{{.ID}} {{.Names}}').splitlines()})
    for _ in range(60):
        if subprocess.run(['docker', 'exec', pg, 'pg_isready', '-U', 'paa'], capture_output=True).returncode == 0:
            break
        time.sleep(.5)
    env = {**os.environ, 'DATABASE_TEST_URL': 'postgresql+psycopg://paa:'+password+'@127.0.0.1:55474/paa_company_test'}
    command(sys.executable, str(BASE / 'environment.py'), 'prepare', '--suite', 'spec074', '--purpose', 'recovery',
            '--output', str(manifest), '--api-url', 'http://127.0.0.1:8024', '--web-origin', 'http://127.0.0.1:5204', env=env)
    command(sys.executable, str(AUDIT / 'configure.py'), '--metadata', str(manifest))
    metadata, private = load_environment(manifest)
    private['environment'].update({'PAA_REPLY_STREAM_REDIS_URL': 'redis://127.0.0.1:56474/0',
        'PAA_SANDBOX_URL': '', 'PAA_SANDBOX_TOKEN': '', 'PAA_WORKER_CONCURRENCY': '3',
        'AGENT_AUDIT_PLAN_INPUT': 'synthetic'})
    save(metadata['secretFile'], private)
    import shlex
    Path(metadata['secretEnvFile']).write_text(''.join(f'export {k}={shlex.quote(v)}\n' for k, v in private['environment'].items()))
    save(output / 'control.json', {})
    print(json.dumps({'prepared': str(manifest), 'ownedContainerIds': [pg, redis]}), flush=True)


def install_faults(control_path, trace):
    """Inject exactly once at a declared external transport boundary."""
    import httpx
    original_send = httpx.AsyncClient.send
    fired = set()
    original_emit = trace.emit

    def observed_emit(kind, **values):
        original_emit(kind, **values)
        try:
            control = json.loads(Path(control_path).read_text())
        except (OSError, ValueError):
            return
        identifier, action = control.get('id'), control.get('action')
        if (kind != 'database_commit' or values.get('table') != 'company_work_item'
                or values.get('operation') != 'insert' or not identifier or identifier in fired
                or action not in ('kill_after_work_commit', 'cancel_after_work_commit')):
            return
        fired.add(identifier)
        original_emit('fault_injected', faultId=identifier, action=action,
                      boundary='after actual database commit of model-requested work insertion',
                      workId=values.get('values',{}).get('id'))
        if action == 'kill_after_work_commit':
            os.kill(os.getpid(), signal.SIGKILL)
        # An owned timing barrier makes the committed-write/cancellation race
        # observable. The model request and database write remain genuine.
        time.sleep(4)

    trace.emit = observed_emit

    async def send(self, request, **kwargs):
        response = await original_send(self, request, **kwargs)
        try:
            control = json.loads(Path(control_path).read_text())
        except (OSError, ValueError):
            control = {}
        identifier = control.get('id')
        external = request.url.host not in ('127.0.0.1', 'localhost', '::1')
        if (identifier and identifier not in fired and control.get('action')=='sandbox-stop'
                and request.url.host=='127.0.0.1' and request.url.port==8025
                and request.method=='GET' and request.url.path.startswith('/executions/')):
            try:
                value=response.json()
            except (ValueError,httpx.ResponseNotRead):
                value={}
            if value.get('state')=='running':
                owner=json.loads((Path(control_path).parent/'ownership.json').read_text())['sandbox']
                project=command('docker','inspect','--format','{{index .Config.Labels "com.docker.compose.project"}}',owner['control'])
                if project!=owner['project']:
                    raise RuntimeError('Sandbox ownership mismatch')
                fired.add(identifier)
                trace.emit('fault_injected',faultId=identifier,action='sandbox-stop',
                           boundary='actual owned sandbox execution observed running',execution=value)
                command('docker','kill',owner['control'])
        if not external or not identifier or identifier in fired:
            return response
        action = control.get('action')
        if action not in ('status403', 'status429', 'status503', 'disconnect', 'malformed', 'empty'):
            return response
        fired.add(identifier)
        trace.emit('fault_injected', faultId=identifier, action=action, actualUpstreamStatus=response.status_code,
                   boundary='after real upstream HTTP response headers; no generated answer injected')
        if action.startswith('status'):
            await response.aclose()
            return httpx.Response(int(action[6:]), request=request,
                                  headers={'retry-after': '1'}, content=b'')
        if action in ('malformed', 'empty'):
            await response.aclose()
            return httpx.Response(200, request=request, headers={'content-type': 'application/json'},
                                  content=b'{' if action == 'malformed' else b'')
        original_stream = response.stream

        class BrokenStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                async for chunk in original_stream:
                    yield chunk
                    raise httpx.ReadError('Spec074 explicit owned stream disconnection', request=request)

            async def aclose(self):
                await original_stream.aclose()

        response.stream = BrokenStream()
        return response

    httpx.AsyncClient.send = send


def launch(output, service):
    output = Path(output).resolve()
    metadata, private = load_environment(output / 'environment.json')
    os.environ.update(private['environment'])
    import trace as audit_trace
    audit_trace.install(output / (service+'.jsonl'))
    install_faults(output / 'control.json', audit_trace)
    audit_trace.emit('runtime_start', service=service, schema=metadata['schema'],
                     applicationCommit=command('git', 'rev-parse', 'HEAD'),
                     appDiffSha256=hashlib.sha256(subprocess.check_output(['git','diff','--','apps','packages'],cwd=ROOT)).hexdigest(),
                     scriptSha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__).resolve(),AUDIT/'launch.py',AUDIT/'trace.py')},
                     workerConcurrency=private['environment'].get('PAA_WORKER_CONCURRENCY'),
                     ownedSandboxUrl=private['environment'].get('PAA_SANDBOX_URL'),
                     faultMode='real upstream then explicitly injected transport failure only')
    if service == 'api':
        import uvicorn
        uvicorn.run('app.main:app', host='127.0.0.1', port=8024, access_log=False)
    else:
        spec = importlib.util.spec_from_file_location('owned_launch', AUDIT / 'launch.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.audit_trace = audit_trace
        asyncio.run(module.worker(metadata['schema']))


def start(output, service):
    output = Path(output).resolve()
    env = {k: v for k, v in os.environ.items() if k.lower() not in ('http_proxy', 'https_proxy', 'all_proxy')}
    log = (output / (service+'.log')).open('a')
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'launch', '--output', str(output), '--service', service],
        cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    log.close()
    save(output / (service+'-process.json'), {'pid': process.pid, 'startedAt': time.time(), 'ownedScript': str(Path(__file__).resolve())})
    print(json.dumps({'service': service, 'pid': process.pid}), flush=True)


def sandbox(output):
    output=Path(output).resolve()
    metadata, private=load_environment(output/'environment.json')
    owner=json.loads((output/'ownership.json').read_text())
    project=owner['tag']+'-sandbox'
    token=secrets.token_urlsafe(32)
    env={**os.environ,'LOCAL_SANDBOX_PROJECT':'noria-sandbox-7b87a5efb0',
         'PAA_SANDBOX_TOKEN':token,'PAA_SANDBOX_LOCAL_PORT':'8025'}
    compose=['docker','compose','-f',str(ROOT/'deploy/company/compose.sandbox-local.yml'),'-p',project]
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',8025))
    command(*compose,'up','-d','--no-build','runtime',env=env)
    engine=command(*compose,'ps','-q','runtime',env=env)
    for _ in range(90):
        if subprocess.run(['docker','exec',engine,'docker','info'],capture_output=True).returncode==0:
            break
        time.sleep(1)
    with (output/'sandbox-setup.log').open('w') as log:
        source=subprocess.Popen(['docker','image','save','noria-sandbox-7b87a5efb0-runner:dev'],stdout=subprocess.PIPE,stderr=log)
        target=subprocess.Popen(['docker','exec','-i',engine,'docker','load'],stdin=source.stdout,stdout=log,stderr=log)
        source.stdout.close()
        target.wait(timeout=180)
        source.wait(timeout=30)
        if source.returncode or target.returncode:
            raise RuntimeError('Owned sandbox runner image import failed')
    command(*compose,'up','-d','--no-build','control',env=env)
    control=command(*compose,'ps','-q','control',env=env)
    owner['sandbox']={'project':project,'runtime':engine,'control':control,'port':8025,
                      'volumes':command('docker','volume','ls','--filter','label=com.docker.compose.project='+project,'--format','{{.Name}}').splitlines()}
    save(output/'ownership.json',owner)
    private['environment'].update(PAA_SANDBOX_URL='http://127.0.0.1:8025',PAA_SANDBOX_TOKEN=token)
    save(metadata['secretFile'],private)
    import shlex
    Path(metadata['secretEnvFile']).write_text(''.join(f'export {k}={shlex.quote(v)}\n' for k,v in private['environment'].items()))
    for service in ('worker','api'):
        pid=json.loads((output/(service+'-process.json')).read_text())['pid']
        process=command('ps','-p',str(pid),'-o','command=')
        if str(Path(__file__).resolve()) not in process or '--service '+service not in process:
            raise RuntimeError('Owned process mismatch')
        os.kill(pid,signal.SIGTERM)
        for _ in range(100):
            if subprocess.run(['kill','-0',str(pid)],capture_output=True).returncode!=0:
                break
            time.sleep(.1)
        start(output,service)
    print(json.dumps({'sandbox':owner['sandbox']}),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'launch', 'start','sandbox'])
    parser.add_argument('--output', required=True)
    parser.add_argument('--service', choices=['api', 'worker'])
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.output)
    elif args.command == 'sandbox':
        sandbox(args.output)
    elif args.command == 'launch':
        launch(args.output, args.service)
    else:
        start(args.output, args.service)
