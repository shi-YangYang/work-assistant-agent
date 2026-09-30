"""Trusted subprocess entrypoint for opt-in execution worker-death testing."""
import asyncio
import json
import os
from pathlib import Path
import sys

if os.environ.get('SPEC042_SANDBOX_TEST') != '1':
    raise SystemExit('Requires isolated test opt-in')
from app.core.config import Settings
from app.db.session import database
from app.tasks.context import RunContext
from app.modules.executions.service import execute


async def main():
    value = json.loads(Path(sys.argv[1]).read_text())
    settings = Settings(database_url=value['database'], media_dir=Path(value['media']), sandbox_url=value['url'], sandbox_token=value['token'])
    engine, sessions = database(settings)
    context = RunContext(value['owner'], value['company'], value['job'], value['fence'], sessions, settings, source_revision=0)
    try:
        await execute(context, code='import time; time.sleep(50)', title='Worker crash probe', references=[])
    finally:
        await engine.dispose()


asyncio.run(main())
