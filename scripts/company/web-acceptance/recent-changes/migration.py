"""Exercise a recoverable backup around retirement in an owned disposable schema."""
import argparse
import asyncio
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path[:0] = [str(HERE.parent), str(ROOT / 'apps/server'), str(ROOT / 'tests/server')]
from environment import load_environment

p = argparse.ArgumentParser()
p.add_argument('--metadata', required=True)
p.add_argument('--output', required=True)
p.add_argument('--resume-backup', action='store_true')
a = p.parse_args()
m, private = load_environment(a.metadata)
assert m['suite'] == 'spec080' and m['purpose'] == 'recovery'
os.environ.update(private['environment'])
from sqlalchemy import create_engine, text, select
from sqlalchemy.engine import make_url
from app.core.config import Settings
from app.db.session import database
from app.modules.members.models import Member
from alembic.operations import Operations
from alembic.migration import MigrationContext

out = Path(a.output)
out.mkdir(exist_ok=True)
schema = m['schema']
engine = create_engine(private['environment']['DATABASE_URL'])

def snapshot():
    with engine.connect() as c:
        names = c.scalars(text('SELECT tablename FROM pg_tables WHERE schemaname=:s ORDER BY tablename'), {'s': schema}).all()
        return {name: sorted(c.scalars(text(f'SELECT row_to_json(t)::text FROM "{schema}"."{name}" t')).all()) for name in names}

async def prepare():
    spec = importlib.util.spec_from_file_location('legacy_fixture', ROOT / 'tests/server/modules/reports/test_daily_report_retirement.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    async_engine, sessions = database(Settings())
    async with sessions.begin() as db:
        actor = await db.get(Member, m['accounts']['employee']['id'])
        rows = await module.legacy_rows(db, actor)
        ids = {'reports': [r.id for r in rows[0]], 'message': rows[1].id, 'work': rows[2].id, 'job': rows[4].id}
    await async_engine.dispose()
    return ids

url = make_url(private['environment']['DATABASE_URL'])
# Local container owns the dedicated test database; never dump the daily schema.
base = ['docker', 'exec', '-i', 'paa-company-postgres-1']
backup = out / 'pre-retirement.sql'
if a.resume_backup:
    dump = backup.read_bytes()
    assert ('CREATE SCHEMA ' + schema).encode() in dump
    with engine.begin() as c:
        c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    subprocess.run(base + ['psql', '-X', '-v', 'ON_ERROR_STOP=1', '-U', url.username, '-d', url.database], input=dump, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    ids = {'resume': 'Original backup retained after test assertion used wrong table name'}
else:
    ids = asyncio.run(prepare())
    dump = subprocess.check_output(base + ['pg_dump', '-U', url.username, '-d', url.database, '--schema', schema, '--no-owner', '--no-privileges'])
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(dump)
before = snapshot()
migration = importlib.import_module('app.migrations.versions.0034_remove_daily_reports')
with engine.begin() as c:
    previous = migration.op
    migration.op = Operations(MigrationContext.configure(c))
    try:
        migration.upgrade()
    finally:
        migration.op = previous
after = snapshot()
assert len(after['company_report']) == len(before['company_report']) - 2
assert before['company_work_item'] == after['company_work_item']
assert before['company_message'] == after['company_message']
# Restore only this marker-verified disposable schema from its own fresh backup.
load_environment(a.metadata)
with engine.begin() as c:
    c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
result = subprocess.run(base + ['psql', '-X', '-v', 'ON_ERROR_STOP=1', '-U', url.username, '-d', url.database], input=dump, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
(out / 'restore.log').write_bytes(result.stdout)
restored = snapshot()
assert restored == before
load_environment(a.metadata)
record = {'schema': schema, 'commit': m['commit'], 'ids': ids, 'backupSha256': hashlib.sha256(dump).hexdigest(), 'beforeCounts': {k:len(v) for k,v in before.items()}, 'afterCounts': {k:len(v) for k,v in after.items()}, 'restoredExactly': restored == before, 'remainingState': 'isolated legacy fixture restored; no service attached'}
(out / 'result.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
print(json.dumps({'schema': schema, 'restoredExactly': True}))
