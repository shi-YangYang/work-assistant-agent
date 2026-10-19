"""Freeze repair comparison inputs and provision independent owned actors.

Only synthetic fixtures and inputs are authored here, never model responses.
The normal serial audit runner performs every interaction with real providers.
"""
import argparse
import asyncio
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from uuid import uuid4

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
sys.path.insert(0, str(HERE.parents[2]))
from environment import load_environment

spec = importlib.util.spec_from_file_location('comparison_setup', HERE / 'prepare-comparisons.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
write = setup.write
BASELINE = '26db8f9bb8af64da403696362b158df7a94ebe1a'


def freeze(output):
    output.mkdir(parents=True, exist_ok=False)
    originals = json.loads((HERE / 'cases.json').read_text())
    performance = json.loads((HERE / 'performance-cases.json').read_text())
    cases = [copy.deepcopy(c) for c in performance if c['group'] == 'chat']
    for identifier in ('T69', 'T64', 'T67', 'T29', 'T09'):
        original = next(c for c in originals if c['id'] == identifier)
        for effort in ('low', 'high'):
            case = copy.deepcopy(original)
            case.update(id=f'R-{identifier}-{effort}', effort=effort,
                        actorRole='admin' if original['role'] == 'realAdmin' else 'employee',
                        matchedOriginal=identifier)
            if identifier == 'T29':
                case['turns'] = case['turns'][:4]
                case['mutationBounds'] = case['mutationBounds'][:4]
                case['goal'] = '根据真实工作生成草稿；修改风险须真实保存；禁止提前提交；明确授权后只提交同一份报告一次'
                case['frozenExpectations'] = {'goal': case['goal'], 'submittedDeletion': 'out of scope'}
            cases.append(case)
    cases += [copy.deepcopy(c) for c in performance if c['group'] == 'multistep' and c['sample'] == 1]
    for case in cases:
        case['role'] = case['id']
        case['cacheCondition'] = 'fresh actor and attachment per side; first processing'
    write(output / 'cases.json', cases, 0o644)
    write(output / 'suite.json', {
        'revision': '074-repair-1', 'caseFile': 'cases.json',
        'caseSha256': hashlib.sha256((output / 'cases.json').read_bytes()).hexdigest(),
        'applicationCommit': BASELINE, 'watchdogSeconds': 1920,
        'highRiskRepetition': {'caseIds': []}, 'modelResponses': 'real-provider-only',
        'firstResults': 'immutable', 'concurrency': 1,
        'quality': 'manual comparison with tool evidence, persisted fields and downloaded files; terminal state alone is not PASS',
    }, 0o644)
    source = ROOT / 'artifacts/spec074/20261017-real-audit'
    known = json.loads((source / 'materials-manifest.json').read_text())
    materials = output / 'materials'
    materials.mkdir()
    hashes = {}
    for name in sorted({name for case in cases for name in case.get('attachments', [])}):
        data = (source / 'materials' / name).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != known[name]['sha256']:
            raise RuntimeError('Original material fingerprint mismatch: ' + name)
        (materials / name).write_bytes(data)
        hashes[name] = {'bytes': len(data), 'sha256': digest}
    write(output / 'materials-manifest.json', hashes, 0o644)
    baseline = Path(tempfile.mkdtemp(prefix='spec074-repair-baseline-'))
    archive = output / 'baseline.tar'
    with archive.open('wb') as stream:
        subprocess.run(['git', 'archive', BASELINE], cwd=ROOT, stdout=stream, check=True)
    subprocess.run(['tar', '-xf', str(archive), '-C', str(baseline)], check=True)
    archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.unlink()
    write(output / 'manifest.json', {
        'baselineCommit': BASELINE, 'baselineSource': str(baseline),
        'baselineArchiveSha256': archive_sha, 'workingSource': str(ROOT),
        'python': str(ROOT / '.venv-server/bin/python'),
        'cases': len(cases), 'turnsPerSide': sum(len(c['turns']) for c in cases),
        'reuse': 'shared installed dependencies only; isolated DB schema, media, Redis namespace and actors',
        'datePolicy': 'normal application date, same-day before/after; report uses current saved work/current week',
        'excluded': ['fault injection', 'provider-generated replacement answers', 'implicit retries'],
    }, 0o644)
    print(json.dumps({'output': str(output), 'baseline': str(baseline), 'cases': len(cases),
                      'turns': sum(len(c['turns']) for c in cases)}))


async def provision(metadata_path, cases_path, source):
    metadata, private = load_environment(metadata_path)
    if metadata.get('suite') != 'spec074':
        raise RuntimeError('Spec074 owned environment required')
    cases = json.loads(cases_path.read_text())
    os.environ.update(private['environment'])
    from app.core.config import Settings
    from app.db import registry
    from app.db.session import database
    from app.modules.members.models import Member
    from pwdlib import PasswordHash
    engine, sessions = database(Settings())
    source_account = private['accounts']['realEmployee']
    password = source_account['password']
    hashed = PasswordHash.recommended().hash(password)
    try:
        async with sessions.begin() as db:
            for case in cases:
                if case['role'] in private['accounts']:
                    raise RuntimeError('Actor already provisioned')
                member = Member(company_id=source_account['companyId'],
                                username='spec074_repair_' + uuid4().hex[:10],
                                name='合成测试 ' + case['id'], role=case['actorRole'], password_hash=hashed)
                db.add(member)
                await db.flush()
                account = {'id': member.id, 'companyId': member.company_id, 'username': member.username,
                           'password': password, 'role': member.role}
                private['accounts'][case['role']] = account
                metadata['accounts'][case['role']] = {k: v for k, v in account.items() if k != 'password'}
        private['environment']['PYTHONPATH'] = os.pathsep.join(str(source / p) for p in ('apps/server', 'packages/voiceprint-engine/src'))
        private['environment']['PAA_WORKER_CONCURRENCY'] = '1'
        metadata['applicationSource'] = str(source)
        metadata['commit'] = BASELINE if source != ROOT else subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        credentials = json.loads(Path(metadata['credentialsFile']).read_text())
        credentials['users'] = private['accounts']
        write(Path(metadata['secretFile']), private)
        write(Path(metadata['credentialsFile']), credentials)
        write(metadata_path, metadata, 0o644)
    finally:
        await engine.dispose()
    print(json.dumps({'schema': metadata['schema'], 'actors': len(cases), 'applicationSource': str(source)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('freeze')
    command.add_argument('--output', required=True, type=Path)
    command = commands.add_parser('provision')
    command.add_argument('--metadata', required=True, type=Path)
    command.add_argument('--cases', required=True, type=Path)
    command.add_argument('--source', required=True, type=Path)
    args = parser.parse_args()
    if args.command == 'freeze':
        freeze(args.output.resolve())
    else:
        asyncio.run(provision(args.metadata.resolve(), args.cases.resolve(), args.source.resolve()))
