"""Owned-runtime launcher and fixed image supplier for the repair A/B experiment."""
import argparse
import asyncio
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import sys

ROOT = Path(__file__).resolve().parents[4]
BASE = ROOT / 'scripts/company/web-acceptance'
sys.path.insert(0, str(BASE))
from environment import load_environment


def install_fixed_images(trace):
    from PIL import Image
    from app.integrations.models.images import wan, results

    async def generate(settings, config, key, prompt, size=None):
        # Both versions pay the same bounded supplier latency; real tool claim,
        # lease, quota, persistence, delivery and model planning remain active.
        await asyncio.sleep(.25)
        identifier = hashlib.sha256(prompt.encode()).hexdigest()
        trace.emit('controlled_image_provider', promptSha256=identifier, size=size)
        return {'request_id': 'controlled-' + identifier,
                'output': {'choices': [{'message': {'content': [{'image': 'https://repair-fixture.invalid/' + identifier + '.png'}]}}]},
                'usage': {}}

    async def download(url):
        if not url.startswith('https://repair-fixture.invalid/'):
            raise RuntimeError('Fixed provider returned an unexpected image URL')
        color = tuple(bytes.fromhex(url.rsplit('/', 1)[1][:6]))
        stream = io.BytesIO()
        Image.new('RGB', (256, 256), color).save(stream, format='PNG')
        data = stream.getvalue()
        return data, results.metadata(data)

    wan.generate_sync = generate
    results.download = download


async def worker(metadata, trace):
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
    key = int(hashlib.sha256(metadata['schema'].encode()).hexdigest()[:7], 16)
    async with await AsyncConnection.connect(settings.checkpoint_url, autocommit=True) as guard:
        if not (await (await guard.execute('SELECT pg_try_advisory_lock(%s)', (key,))).fetchone())[0]:
            raise RuntimeError('Owned worker already active')
        timer = asyncio.create_task(scheduler(sessions, settings))
        voices = asyncio.create_task(worker_loop(sessions, settings, stop))
        try:
            await run_slots(sessions, settings, stop, runner=trace.observe_job(process_job))
        finally:
            timer.cancel()
            voices.cancel()
            await asyncio.gather(timer, voices, return_exceptions=True)
            from app.tasks.streaming.redis_store import close_stores
            await close_stores()
            await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--trace', required=True)
    parser.add_argument('service', choices=['api', 'worker'])
    args = parser.parse_args()
    metadata, private = load_environment(args.metadata)
    if metadata['suite'] != 'spec068' or metadata['purpose'] != 'baseline':
        raise RuntimeError('Exact repair environment required')
    os.environ.update(private['environment'])
    source = Path(args.source).resolve()
    sys.path[:0] = [str(source / 'apps/server'), str(source / 'packages/voiceprint-engine/src')]
    specification = importlib.util.spec_from_file_location('repair_audit_trace', BASE / 'agent-audit/trace.py')
    trace = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(trace)
    trace.install(args.trace)
    install_fixed_images(trace)
    from app.tasks.timing import Timing
    original_mark = Timing.mark
    def observed_mark(self, event, **fields):
        value = original_mark(self, event, **fields)
        if event in ('model.send', 'model.first_body', 'model.end'):
            trace.emit('repair_timing', timing=value)
        return value
    Timing.mark = observed_mark
    from app.core import config
    if Path(config.__file__).resolve() != source / 'apps/server/app/core/config.py':
        raise RuntimeError('Version isolation failed')
    trace.emit('repair_runtime_start', service=args.service, source=str(source),
               sourceManifestSha256=hashlib.sha256((source.parent / (source.name + '-hashes.json')).read_bytes()).hexdigest())
    if args.service == 'api':
        import uvicorn
        uvicorn.run('app.main:app', host='127.0.0.1', port=int(metadata['apiOrigin'].rsplit(':', 1)[1]), access_log=False)
    else:
        asyncio.run(worker(metadata, trace))


if __name__ == '__main__':
    main()
