"""Freeze explicit report-save follow-up after the original prompt branched in meaning."""
import asyncio
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / 'artifacts/spec068/repair-performance'
sys.path.insert(0, str(ROOT/'scripts/company/web-acceptance'))
from environment import load_environment


async def main():
    if (OUT/'cases-explicit-report.json').exists():
        raise RuntimeError('Explicit report fixtures are already frozen')
    resources = json.loads((OUT/'resources.json').read_text())
    original = json.loads((OUT/'cases.json').read_text())
    common = []
    now = datetime.now(timezone.utc)
    for pair in original['pairs']:
        if pair['id'] == 'report':
            common.append({**pair, 'alias': pair['alias'].replace('report-', 'report-explicit-'),
                'prompt': '根据我已经有的工作，在 Noria 的“我的报告”里创建并保存本周周报草稿，不要提交。请完成保存后告诉我结果。',
                'actorId': str(uuid4()), 'fixtureWorkId': str(uuid4()),
                'expectations': ['实际保存且只有一份本周周报草稿', '已核对5份、余2份事实准确', '没有提交或修改工作', '报告子任务真正完成且taskOutcome不含已纠正错误']})
    from app.core.config import Settings
    from app.db import registry
    from app.db.session import database
    from app.modules.members.models import Member
    from app.modules.work.models import WorkItem, WorkRevision
    for version in ('baseline', 'candidate'):
        metadata, private = load_environment(resources['manifests'][version])
        os.environ.update(private['environment'])
        engine, sessions = database(Settings())
        async with sessions.begin() as db:
            parent = await db.get(Member, private['accounts']['employee']['id'])
            for pair in common:
                username = 's068perf_' + pair['actorId'].replace('-', '')[:18]
                actor = Member(id=pair['actorId'], company_id=parent.company_id, username=username,
                    name='合成性能用户', role='employee', password_hash=parent.password_hash,
                    execution_mode='auto', full_access_confirmed=False, created_at=now)
                db.add(actor)
                await db.flush()
                private['accounts'][pair['alias']] = {'id': actor.id, 'companyId': actor.company_id,
                    'username': username, 'password': private['accounts']['employee']['password'], 'role': 'employee'}
                work = WorkItem(id=pair['fixtureWorkId'], company_id=actor.company_id, owner_id=actor.id,
                    title=pair['work']['title'], content=pair['work'], created_at=now, updated_at=now)
                db.add(work)
                await db.flush()
                db.add(WorkRevision(id=str(uuid4()), company_id=actor.company_id, owner_id=actor.id, work_id=work.id,
                    revision=1, content=pair['work'], source_ids=[], created_at=now))
        await engine.dispose()
        Path(metadata['secretFile']).write_text(json.dumps(private, ensure_ascii=False, indent=2))
    accepted = [p for p in original['pairs'] if p['id'] == 'ordinary' or p['id'] == 'report' and p['effort'] == 'low']
    merged = {**original, 'pairs': [*accepted, *common, *[p for p in original['pairs'] if p['id'] == 'images']],
              'observations': 28, 'comparableObservations': 24, 'diagnosticObservations': 4,
              'originalPromptDiagnostic': 'Original four low report observations retained. Two text-only drafts and durable report creation are different outcomes and not timing comparators.',
              'unexecutedOriginalCases': [p['alias'] for p in original['pairs'] if p['id'] == 'report' and p['effort'] == 'high'],
              'followupReason': 'Explicit user-authorized report-save intent resolves original prompt ambiguity; no resampling based on speed or output quality.'}
    (OUT/'cases-explicit-report.json').write_text(json.dumps(merged, ensure_ascii=False, indent=2))
    print(json.dumps({'frozen': True, 'newIndependentActorsPerVersion': 4, 'newObservations': 8}))


if __name__ == '__main__':
    asyncio.run(main())
