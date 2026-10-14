"""Trusted process using production worker slots with a deterministic IO barrier."""
import asyncio
import json
import os
import re
from pathlib import Path
import sys

from sqlalchemy.engine import make_url
from app.core.config import Settings
from app.db import registry
from app.db.session import database
from app.modules.members.models import Member
from app.modules.work.commands import create_work_command
from app.modules.work.schemas import Progress
from app.tasks.models import Job
from app.tasks.runtime.runner import run_slots


def checked_target(settings):
    run_id = os.environ.get('SPEC044_RUN_ID', '')
    if not re.fullmatch(r'[a-f0-9]{32}', run_id):
        raise SystemExit('Requires isolated acceptance environment')
    if os.environ.get('PAA_AGENT_FAULT_ENVIRONMENT'):
        # Validates the exact database, schema, owner marker and private manifest;
        # a new audit suite must never become a broad search_path prefix bypass.
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts/company/web-acceptance/agent-audit'))
        from faults import isolated_url
        url = isolated_url(settings)
        metadata = json.loads(Path(os.environ['PAA_AGENT_FAULT_ENVIRONMENT']).read_text())
        if metadata['runId'] != run_id:
            raise SystemExit('Worker run does not match the owned environment')
        return url
    url = make_url(settings.database_url)
    if (url.database != 'paa_company_test' or url.host not in ('127.0.0.1', 'localhost')
            or not re.fullmatch(r'-csearch_path=spec(?:044|054)_[a-z]+_' + run_id[:12], url.query.get('options', ''))):
        raise SystemExit('Refusing unsafe DB target')
    return url


async def main():
    settings = Settings()
    checked_target(settings)
    control = json.loads(Path(sys.argv[1]).read_text())
    phase = sys.argv[2]
    marker_dir = Path(control['markers'])
    engine, sessions = database(settings)
    stop = asyncio.Event()
    async def deterministic(job, sessions, settings, saver):
        boundary = control['jobs'].get(job.id)
        if boundary is None:
            raise RuntimeError('Unexpected job in isolated worker fixture')
        if phase == 'crash' and boundary == 'before_write':
            (marker_dir / job.id).write_text(boundary)
            await asyncio.Event().wait()
        async with sessions.begin() as db:
            actor = await db.get(Member, job.owner_id)
            result = await create_work_command(Progress(title='恢复唯一工作 ' + boundary, summary='合成业务写入'), job.id, actor, db)
        if phase == 'crash' and boundary == 'after_write':
            (marker_dir / job.id).write_text(boundary)
            await asyncio.Event().wait()
        async with sessions.begin() as db:
            live = await db.get(Job, job.id)
            assert live.fence == job.fence and live.state == 'running'
            live.state, live.lease_until, live.result = 'succeeded', None, {'workId': result['id'], 'boundary': boundary}
        if phase == 'crash':
            (marker_dir / job.id).write_text(boundary)
            await asyncio.Event().wait()
        # All three persisted terminal states must exist before this process exits.
        from sqlalchemy import select
        async with sessions() as db:
            states = (await db.scalars(select(Job.state).where(Job.id.in_(control['jobs'])))).all()
        if states == ['succeeded'] * len(control['jobs']):
            stop.set()
    try:
        await asyncio.wait_for(run_slots(sessions, settings, stop, runner=deterministic, shutdown_timeout=1), 125)
    finally:
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
