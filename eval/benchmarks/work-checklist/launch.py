"""Launch an owned benchmark against an exact independent application directory."""
import argparse
import asyncio
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import signal
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts/company/web-acceptance'))
from environment import load_environment


def source_digest(source):
    digest = hashlib.sha256()
    for folder in ('apps/server/app', 'packages/voiceprint-engine/src'):
        for path in sorted((source / folder).rglob('*.py')):
            if '__pycache__' not in path.parts:
                digest.update(str(path.relative_to(source)).encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()


async def worker(schema, trace):
    from app.core.config import Settings
    from app.db.session import database
    from app.tasks.maintenance.maintenance import scheduler
    from app.tasks.runtime.runner import run_slots
    from app.tasks.processing.handlers import process_job
    from psycopg import AsyncConnection
    settings = Settings()
    engine, sessions = database(settings)
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    key = int(hashlib.sha256(schema.encode()).hexdigest()[:7], 16)
    async with await AsyncConnection.connect(settings.checkpoint_url, autocommit=True) as guard:
        if not (await (await guard.execute('SELECT pg_try_advisory_lock(%s)', (key,))).fetchone())[0]:
            raise RuntimeError('Owned worker already running')
        timer = asyncio.create_task(scheduler(sessions, settings))
        try:
            await run_slots(sessions, settings, stop, runner=trace.observe_job(process_job))
        finally:
            timer.cancel()
            await asyncio.gather(timer, return_exceptions=True)
            from app.tasks.streaming.redis_store import close_stores
            await close_stores()
            await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--trace', required=True)
    parser.add_argument('service', choices=('api', 'worker'))
    args = parser.parse_args()
    metadata, private = load_environment(args.metadata)
    if metadata.get('suite') not in ('spec063', 'spec079'):
        raise RuntimeError('Exact work benchmark ownership required')
    source = Path(args.source).resolve()
    if not (source / 'apps/server/app/main.py').is_file():
        raise RuntimeError('Application source missing')
    os.environ.update(private['environment'])
    for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
        os.environ.pop(key, None)
    os.environ['PAA_WORKER_CONCURRENCY'] = '1'
    os.environ['AGENT_AUDIT_PLAN_INPUT'] = 'synthetic'
    # environment.py only imports SQLAlchemy helpers. Put frozen application first
    # before any app import; no shared app module is loaded in this process.
    sys.path[:0] = [str(source / 'apps/server'), str(source / 'packages/voiceprint-engine/src')]
    trace_path = source / 'eval/web/agent-audit/trace.py'
    if not trace_path.is_file():
        # Frozen baseline checkouts predate the eval directory migration.
        trace_path = source / 'scripts/company/web-acceptance/agent-audit/trace.py'
    spec = importlib.util.spec_from_file_location('checklist_trace', trace_path)
    trace = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trace)
    trace.install(args.trace)
    import app.core.config
    if not Path(app.core.config.__file__).is_relative_to(source):
        raise RuntimeError('Application escaped frozen source')
    trace.emit('runtime_start', service=args.service, schema=metadata['schema'], sourceRoot=str(source), sourceSha256=source_digest(source), configModule=app.core.config.__file__)
    logging.basicConfig(level=logging.INFO)
    if args.service == 'api':
        import uvicorn
        uvicorn.run('app.main:app', host='127.0.0.1', port=int(metadata['apiOrigin'].rsplit(':', 1)[1]), access_log=False)
    else:
        asyncio.run(worker(metadata['schema'], trace))


if __name__ == '__main__':
    main()
