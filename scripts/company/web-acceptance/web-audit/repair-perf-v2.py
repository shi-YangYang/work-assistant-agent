"""Prepare the pre-agreed 16 v2 observations without issuing any model request."""
import argparse
import asyncio
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT/'artifacts/spec068/repair-performance'
V2 = OUT/'v2'
sys.path.insert(0, str(ROOT/'scripts/company/web-acceptance'))
from environment import load_environment


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def setup_module():
    spec = importlib.util.spec_from_file_location('repair_setup', Path(__file__).with_name('repair-perf-setup.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.OUT = V2
    return module


async def prepare():
    if V2.exists():
        raise RuntimeError('Refusing to replace an existing v2 campaign')
    V2.mkdir()
    resources = json.loads((OUT/'resources.json').read_text())
    for item in json.loads((OUT/'run.json').read_text())['processes']:
        process = subprocess.run(['ps', '-p', str(item['pid']), '-o', 'command='], text=True, capture_output=True)
        if 'repair-perf-runtime.py' in process.stdout:
            raise RuntimeError('Previous owned runtime must be stopped')
    write(V2/'resources.json', {**resources, 'reuseFrom': str(OUT), 'cleanupOwner': str(OUT), 'purpose': 'fixed v2 follow-up'})
    prior = json.loads((OUT/'cases-explicit-report.json').read_text())
    pairs = []
    for case in prior['pairs']:
        if case['id'] == 'ordinary' or case['alias'] in ('report-low-1', 'report-low-2'):
            continue
        pair = {**case, 'alias': 'v2-' + case['alias'], 'actorId': str(uuid4())}
        if case['id'] == 'report':
            pair.update(fixtureWorkId=str(uuid4()), fixtureWorkRevisionId=str(uuid4()))
            pair['expectations'] = [*pair['expectations'], '最终公开卡片成功、taskOutcome完成且回复无仍在处理的矛盾说明']
        else:
            pair['expectations'] = [*pair['expectations'], '记录参数纠正次数与多余模型往返，不隐藏失败']
        pairs.append(pair)
    frozen = {key: value for key, value in prior.items() if key not in ('pairs', 'originalPromptDiagnostic', 'unexecutedOriginalCases', 'followupReason')}
    frozen.update(version=2, candidateLabel='v2', observations=16, comparableObservations=16, diagnosticObservations=0,
                  pairs=pairs, frozenBeforeAnyModelCalls=True, concurrency=1,
                  followupReason='Coordinator pre-authorized targeted report/image revalidation only; v1 ordinary remains unchanged and is not resampled.',
                  candidateSourceStatus='awaiting final coordinator freeze signal')
    write(V2/'cases.json', frozen)
    # Full baseline archive is safe to freeze before the final candidate exists.
    setup_module().freeze('baseline')
    sys.path.insert(0, str(V2/'baseline/apps/server'))
    from app.core.config import Settings
    from app.db import registry
    from app.db.session import database
    from app.modules.members.models import Member
    from app.modules.work.models import WorkItem, WorkRevision
    created_at = datetime.now(timezone.utc)
    for version in ('baseline', 'candidate'):
        metadata, private = load_environment(resources['manifests'][version])
        os.environ.update(private['environment'])
        engine, sessions = database(Settings())
        async with sessions.begin() as db:
            template = await db.get(Member, private['accounts']['employee']['id'])
            for pair in pairs:
                actor = Member(id=pair['actorId'], company_id=template.company_id,
                    username='s068v2_' + pair['actorId'].replace('-', '')[:18], name='合成性能用户',
                    role='employee', password_hash=template.password_hash, execution_mode='auto',
                    full_access_confirmed=False, created_at=created_at)
                db.add(actor)
                await db.flush()
                private['accounts'][pair['alias']] = {'id': actor.id, 'companyId': actor.company_id,
                    'username': actor.username, 'password': private['accounts']['employee']['password'], 'role': 'employee'}
                if pair['id'] == 'report':
                    db.add(WorkItem(id=pair['fixtureWorkId'], company_id=actor.company_id, owner_id=actor.id,
                        title=pair['work']['title'], content=pair['work'], created_at=created_at, updated_at=created_at))
                    await db.flush()
                    db.add(WorkRevision(id=pair['fixtureWorkRevisionId'], company_id=actor.company_id,
                        owner_id=actor.id, work_id=pair['fixtureWorkId'], revision=1, content=pair['work'], source_ids=[], created_at=created_at))
        await engine.dispose()
        # Add only distinct v2 accounts; never overwrite the original experiment actors.
        Path(metadata['secretFile']).write_text(json.dumps(private, ensure_ascii=False, indent=2))
    write(V2/'preparation.json', {'prepared': True, 'sourceReady': False, 'modelRequests': 0,
        'casesSha256': hashlib.sha256((V2/'cases.json').read_bytes()).hexdigest(),
        'independentActorsPerVersion': len(pairs), 'baselineSha': '0fd76fed8400d064d2585c4e753d542343eb864f',
        'retainedV1': True, 'fixtureCreatedAt': created_at.isoformat()})
    print(json.dumps({'prepared': True, 'observations': 16, 'modelRequests': 0, 'awaitingCandidateFreeze': True}))


def freeze():
    # Invoke only after the coordinator's final source freeze signal.
    module = setup_module()
    module.freeze('candidate')
    preparation = json.loads((V2/'preparation.json').read_text())
    preparation['sourceReady'] = True
    preparation['candidateManifestSha256'] = hashlib.sha256((V2/'candidate-hashes.json').read_bytes()).hexdigest()
    write(V2/'preparation.json', preparation)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'freeze'])
    args = parser.parse_args()
    if args.command == 'prepare':
        asyncio.run(prepare())
    else:
        freeze()
