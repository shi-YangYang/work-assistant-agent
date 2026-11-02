"""Launch exact application code with isolated observers, not production config."""
import argparse
import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
import signal
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts/company/web-acceptance'))
from environment import load_environment


async def worker(schema):
    from app.core.config import Settings
    from app.db import registry
    from app.db.session import database
    from app.tasks.maintenance.maintenance import scheduler
    from app.tasks.runtime.runner import run_slots
    from app.tasks.processing.voiceprints import worker_loop
    from app.tasks.processing.handlers import process_job
    from psycopg import AsyncConnection
    settings = Settings()
    engine, sessions = database(settings)
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    # Same exclusivity semantics, scoped to the disposable test schema.
    key = int(hashlib.sha256(schema.encode()).hexdigest()[:7], 16)
    async with await AsyncConnection.connect(settings.checkpoint_url, autocommit=True) as guard:
        if not (await (await guard.execute('SELECT pg_try_advisory_lock(%s)', (key,))).fetchone())[0]:
            raise RuntimeError('Isolated worker already running')
        timer = asyncio.create_task(scheduler(sessions, settings))
        voices = asyncio.create_task(worker_loop(sessions, settings, stop))
        try:
            await run_slots(sessions, settings, stop, runner=audit_trace.observe_job(process_job))
        finally:
            timer.cancel()
            voices.cancel()
            await asyncio.gather(timer, voices, return_exceptions=True)
            from app.tasks.streaming.redis_store import close_stores
            await close_stores()
            await engine.dispose()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--metadata', required=True)
    p.add_argument('--trace', required=True)
    p.add_argument('service', choices=['api', 'worker'])
    args = p.parse_args()
    metadata, private = load_environment(args.metadata)
    os.environ.update(private['environment'])
    import trace as audit_trace
    audit_trace.install(args.trace)
    import importlib.metadata
    import subprocess
    runtime_versions = {}
    for package in ('deepagents', 'langgraph', 'langchain', 'langchain-openai', 'sqlalchemy', 'httpx', 'psycopg'):
        try:
            runtime_versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            runtime_versions[package] = 'unavailable'
    root = Path(__file__).resolve().parents[3]
    application_paths = subprocess.check_output(['git', 'ls-files', '-co', '--exclude-standard', '--', 'apps', 'packages'], cwd=root, text=True).splitlines()
    application_source = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sorted(set(application_paths)) if (root / name).is_file()}
    audit_trace.emit('runtime_start', applicationSource=[{'path': name, 'sha256': value} for name, value in application_source.items()], service=args.service, schema=metadata['schema'],
                     applicationCommit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                     appDiffSha256=hashlib.sha256(subprocess.check_output(['git', 'diff', '--', 'apps', 'packages'])).hexdigest(),
                     scriptSha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')},
                     dependencies=runtime_versions)
    logging.basicConfig(level=logging.INFO)
    if args.service == 'api':
        import uvicorn
        uvicorn.run('app.main:app', host='127.0.0.1', port=int(metadata['apiOrigin'].rsplit(':', 1)[1]), access_log=False)
    else:
        asyncio.run(worker(metadata['schema']))
