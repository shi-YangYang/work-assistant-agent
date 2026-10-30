"""Freeze source and prepare/clean exact independent PostgreSQL/Redis A/B runtimes."""
import argparse
import asyncio
import copy
import hashlib
import json
import io
import tarfile
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[4]
BASE = ROOT / 'scripts/company/web-acceptance'
OUT = ROOT / 'artifacts/spec068/repair-performance'
sys.path.insert(0, str(BASE))
from environment import load_environment, private_json


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def clean_env():
    return {k: v for k, v in os.environ.items() if k.lower() not in ('http_proxy', 'https_proxy', 'all_proxy')}


def command(args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def freeze(version):
    source = OUT / version
    if source.exists():
        raise RuntimeError('Refusing to replace a frozen source')
    source.mkdir()
    archive = subprocess.check_output(['git', 'archive', '0fd76fed8400d064d2585c4e753d542343eb864f'], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        stream.extractall(source, filter='data')
    if version == 'candidate':
        names = command(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '--', 'apps/server', 'packages'], cwd=ROOT).splitlines()
        for name in names:
            original, target = ROOT / name, source / name
            if original.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, target)
            elif target.is_file():
                target.unlink()
    hashes = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in source.rglob('*') if p.is_file() and '.git' not in p.parts}
    write(OUT / (version + '-hashes.json'), hashes)
    for p in source.rglob('*'):
        p.chmod(p.stat().st_mode & ~0o222)
    source.chmod(source.stat().st_mode & ~0o222)
    print(json.dumps({'version': version, 'frozenFiles': len(hashes)}))


async def seed_pairs(path):
    from app.core.config import Settings
    from app.db import registry
    from app.db.session import database
    from app.modules.members.models import Member
    from app.modules.work.models import WorkItem, WorkRevision
    from app.modules.model_services.models import ModelService, ModelServiceRevision
    from sqlalchemy import select
    metadata, private = load_environment(path)
    os.environ.update(private['environment'])
    engine, sessions = database(Settings())
    cases = [
        {'id': 'ordinary', 'prompt': '用三句话解释浏览器缓存是什么，不用联网，也不要创建工作或报告。',
         'expectations': ['解释浏览器缓存', '无业务写入', '正常成功且不声称工具执行']},
        {'id': 'report', 'prompt': '根据我已经有的工作起草本周周报，先给草稿，不提交。',
         'expectations': ['只有一份本周周报草稿', '已核对5份、余2份事实准确', '没有提交或修改工作', 'taskOutcome 无已纠正错误'],
         'work': {'title': '资料核对-R01', 'summary': '已核对5份客户资料，尚余2份', 'status': 'in_progress', 'nextStep': '核对剩余2份'}},
        {'id': 'images', 'prompt': '请生成四张3D猫和老鼠图片，分别是一起喝茶、追逐奶酪、躲猫猫、分享蛋糕。放在同一个任务里，直接生成，不要只写提示词。',
         'expectations': ['四张文件、四次实际供应调用', '一次任务成果', '各画面请求对应四种描述', '无未授权工作或报告写入', '无未完成状态']},
    ]
    pairs = []
    async with sessions.begin() as db:
        original = await db.get(Member, private['accounts']['employee']['id'])
        for case in cases:
            for effort in ('low', 'high'):
                for repetition in (1, 2):
                    alias = f"{case['id']}-{effort}-{repetition}"
                    actor = Member(company_id=original.company_id, username='s068perf_' + uuid4().hex[:18],
                        name='合成性能用户', role='employee', password_hash=original.password_hash,
                        execution_mode='auto', full_access_confirmed=False)
                    db.add(actor)
                    await db.flush()
                    private['accounts'][alias] = {'id': actor.id, 'companyId': actor.company_id,
                        'username': actor.username, 'password': private['accounts']['employee']['password'], 'role': 'employee'}
                    row = {**case, 'alias': alias, 'effort': effort, 'repetition': repetition,
                           'order': ['baseline', 'candidate'] if repetition == 1 else ['candidate', 'baseline'],
                           'persona': 'dabao', 'executionMode': 'auto'}
                    if case.get('work'):
                        work = WorkItem(company_id=actor.company_id, owner_id=actor.id, title=case['work']['title'], content=case['work'])
                        db.add(work)
                        await db.flush()
                        db.add(WorkRevision(company_id=actor.company_id, owner_id=actor.id, work_id=work.id, revision=1,
                                           content=case['work'], source_ids=[]))
                        row['fixtureWorkId'] = work.id
                    pairs.append(row)
        # Keep protocol validation intact but force controlled synchronous supplier.
        for model_class in (ModelService, ModelServiceRevision):
            for service in await db.scalars(select(model_class)):
                models = copy.deepcopy(service.models)
                for model in models:
                    if model.get('protocol') == 'dashscope-image':
                        model['imageSettings'] = {'api': 'multimodal-sync', 'sizeMode': 'auto'}
                service.models = models
    await engine.dispose()
    Path(metadata['secretFile']).write_text(json.dumps(private, ensure_ascii=False, indent=2))
    write(OUT / 'cases.json', {'version': 1, 'frozenBeforeAnyModelCalls': True,
          'imageSupplier': 'test-process adapter: 250ms fixed + 256x256 PNG, not real image generation latency',
          'runtime': 'real HTTP API -> worker -> real text model; real report/image persistence and authorization',
          'timing': 'HTTP send to SSE first body and durable GET terminal; no browser paint',
          'repetitionsPerEffortVersion': 2, 'observations': 24, 'watchdogSeconds': 1200, 'pairs': pairs})


def prepare():
    if (OUT / 'resources.json').exists():
        raise RuntimeError('Owned environment already exists')
    OUT.mkdir(parents=True, exist_ok=True)
    run = uuid4().hex[:12]
    resources = {'run': run, 'containers': {}, 'processes': [], 'manifests': {}}
    write(OUT / 'resources.json', resources)
    for label, image, inner in [('baseline', 'postgres:17.11-bookworm', 5432), ('candidate', 'postgres:17.11-bookworm', 5432), ('redis', 'redis:7.4-alpine', 6379)]:
        name = f'noria-spec068-repair-{run}-{label}'
        args = ['docker', 'run', '-d', '--name', name, '--label', 'noria.spec068.repair=' + run,
                '-p', f'127.0.0.1::{inner}']
        if label != 'redis':
            args += ['-e', 'POSTGRES_DB=paa_company_test', '-e', 'POSTGRES_USER=audit', '-e', 'POSTGRES_PASSWORD=audit']
        identifier = command([*args, image])
        data = json.loads(command(['docker', 'inspect', identifier]))[0]
        port = int(data['NetworkSettings']['Ports'][str(inner)+'/tcp'][0]['HostPort'])
        resources['containers'][label] = {'id': identifier, 'name': name, 'port': port, 'image': image}
        write(OUT / 'resources.json', resources)
        if label != 'redis':
            for _ in range(100):
                if subprocess.run(['docker', 'exec', identifier, 'pg_isready', '-U', 'audit', '-d', 'paa_company_test'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                    break
                time.sleep(.1)
            else:
                raise RuntimeError('Owned PostgreSQL failed to start')
    port = resources['containers']['baseline']['port']
    directory = OUT / 'runtime-baseline'
    directory.mkdir()
    manifest = directory / 'manifest.json'
    env = {**clean_env(), 'DATABASE_TEST_URL': f'postgresql+psycopg://audit:audit@127.0.0.1:{port}/paa_company_test'}
    with (directory / 'prepare.log').open('w') as log:
        subprocess.run([sys.executable, str(BASE / 'environment.py'), 'prepare', '--suite', 'spec068', '--purpose', 'baseline', '--output', str(manifest), '--api-url', f'http://127.0.0.1:{free_port()}'], env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run([sys.executable, str(ROOT / 'eval/web/agent-audit/configure.py'), '--metadata', str(manifest)], env=clean_env(), stdout=log, stderr=subprocess.STDOUT, check=True)
    metadata, private = load_environment(manifest)
    private['environment'].update(PAA_REPLY_STREAM_REDIS_URL=f"redis://127.0.0.1:{resources['containers']['redis']['port']}/0",
        PAA_REPLY_STREAM_NAMESPACE='spec068:repair:' + run + ':baseline', PAA_SANDBOX_URL='', PAA_SANDBOX_TOKEN='',
        PAA_WORKER_CONCURRENCY='1', PYTHONDONTWRITEBYTECODE='1')
    Path(metadata['secretFile']).write_text(json.dumps(private, ensure_ascii=False, indent=2))
    asyncio.run(seed_pairs(manifest))
    metadata, private = load_environment(manifest)
    # Same schema, IDs, credentials, timestamps, model configuration and fixtures.
    dump = subprocess.check_output(['docker', 'exec', resources['containers']['baseline']['id'], 'pg_dump', '-U', 'audit', '-d', 'paa_company_test', '--no-owner'])
    restored = subprocess.run(['docker', 'exec', '-i', resources['containers']['candidate']['id'], 'psql', '-U', 'audit', '-d', 'paa_company_test', '-v', 'ON_ERROR_STOP=1'], input=dump, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if restored.returncode:
        raise RuntimeError('Owned clone restore failed')
    candidate_dir = OUT / 'runtime-candidate'
    candidate_dir.mkdir()
    candidate = copy.deepcopy(metadata)
    privdir = Path(tempfile.mkdtemp(prefix=metadata['schema'] + '_')).resolve()
    candidate.update(apiOrigin=f'http://127.0.0.1:{free_port()}', privateDirectory=str(privdir),
        secretFile=str(privdir/'environment.json'), secretEnvFile=str(privdir/'environment.env'),
        credentialsFile=str(candidate_dir/'credentials.json'))
    candidate['apiUrl'] = candidate['apiOrigin']
    cloned = copy.deepcopy(private)
    source_env = private['environment']
    cloned_env = cloned['environment']
    cloned_env['DATABASE_URL'] = source_env['DATABASE_URL'].replace(f':{port}/', f":{resources['containers']['candidate']['port']}/")
    cloned_env['DATABASE_TEST_URL'] = cloned_env['DATABASE_URL']
    cloned_env['PAA_MEDIA_DIR'] = str(privdir/'media')
    cloned_env['PAA_MODEL_KEY_FILE'] = str(privdir/'master.key')
    cloned_env['PAA_REPLY_STREAM_NAMESPACE'] = 'spec068:repair:' + run + ':candidate'
    shutil.copy2(source_env['PAA_MODEL_KEY_FILE'], cloned_env['PAA_MODEL_KEY_FILE'])
    private_json(privdir/'environment.json', cloned)
    private_json(candidate_dir/'credentials.json', {'unused': True})
    private_json(privdir/'environment.env', {})
    write(candidate_dir/'manifest.json', candidate)
    resources['manifests'] = {'baseline': str(manifest), 'candidate': str(candidate_dir/'manifest.json')}
    write(OUT / 'resources.json', resources)
    print(json.dumps({'prepared': True, 'observations': 24, 'ownedContainers': len(resources['containers'])}))


def cleanup():
    resources = json.loads((OUT/'resources.json').read_text())
    findings = []
    for run_path in (OUT/'run.json', OUT/'v2/run.json'):
        if not run_path.exists():
            continue
        for item in json.loads(run_path.read_text())['processes']:
            process = subprocess.run(['ps', '-p', str(item['pid']), '-o', 'command='], text=True, capture_output=True)
            if process.returncode == 0 and 'repair-perf-runtime.py' in process.stdout and str(run_path.parent/item['version']) in process.stdout:
                raise RuntimeError('Owned runtime is still running; stop it before cleanup')
            findings.append({'pid': item['pid'], 'ownedRuntimeStopped': True})
    for version, path in resources['manifests'].items():
        with (OUT/f'cleanup-{version}.log').open('w') as log:
            result = subprocess.run([sys.executable, str(BASE/'environment.py'), 'cleanup', '--metadata', path], env=clean_env(), stdout=log, stderr=subprocess.STDOUT)
        findings.append({'version': version, 'schemaAndSecretsCleanupExit': result.returncode})
        if result.returncode:
            write(OUT/'cleanup.json', {'findings': findings, 'allOwned': True, 'complete': False})
            raise RuntimeError('Owned schema or secret cleanup failed')
    for item in resources['containers'].values():
        data = json.loads(command(['docker', 'inspect', item['id']]))[0]
        if data['Config']['Labels'].get('noria.spec068.repair') != resources['run']:
            raise RuntimeError('Container ownership changed')
        command(['docker', 'rm', '-f', item['id']])
        findings.append({'container': item['name'], 'removed': True})
    for version in ('baseline', 'candidate', 'v2/baseline', 'v2/candidate'):
        source = OUT/version
        if source.exists():
            for p in source.rglob('*'):
                p.chmod(p.stat().st_mode | 0o700)
            source.chmod(0o700)
            shutil.rmtree(source)
            findings.append({'source': version, 'removed': True, 'hashManifestRetained': True})
    write(OUT/'cleanup.json', {'findings': findings, 'allOwned': True})
    print(json.dumps({'cleaned': True}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'freeze-baseline', 'freeze-candidate', 'cleanup'])
    args = parser.parse_args()
    if args.command.startswith('freeze-'):
        freeze(args.command.removeprefix('freeze-'))
    else:
        globals()[args.command]()
