"""Run the normal API/worker from an explicitly frozen source with real observers."""
import argparse
import asyncio
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
AUDIT = HERE.parents[1]
sys.path.insert(0, str(AUDIT.parents[2] / 'scripts/company/web-acceptance'))
from environment import load_environment, ROOT


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', required=True)
    parser.add_argument('--trace', required=True)
    parser.add_argument('service', choices=['api', 'worker'])
    args = parser.parse_args()
    metadata, private = load_environment(args.metadata)
    source = Path(metadata['applicationSource']).resolve()
    os.environ.update(private['environment'])
    for path in (ROOT / 'apps/server', ROOT / 'packages/voiceprint-engine/src'):
        while str(path) in sys.path:
            sys.path.remove(str(path))
    sys.path[:0] = [str(source / 'apps/server'), str(source / 'packages/voiceprint-engine/src'), str(AUDIT)]
    import app
    if Path(app.__file__).resolve() != source / 'apps/server/app/__init__.py':
        raise RuntimeError('Wrong application source selected')
    trace = module('repair_audit_trace', AUDIT / 'trace.py')
    trace.install(args.trace)
    files = sorted(p for folder in ('apps/server/app', 'packages/voiceprint-engine/src') for p in (source / folder).rglob('*.py'))
    hashes = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    trace.emit('runtime_start', service=args.service, schema=metadata['schema'],
               applicationCommit=metadata['commit'], applicationSource=str(source), importedApp=app.__file__,
               sourceTreeSha256=hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest())
    logging.basicConfig(level=logging.INFO)
    if args.service == 'api':
        import uvicorn
        uvicorn.run('app.main:app', host='127.0.0.1', port=int(metadata['apiOrigin'].rsplit(':', 1)[1]), access_log=False)
    else:
        launcher = module('repair_normal_worker', AUDIT / 'launch.py')
        launcher.audit_trace = trace
        asyncio.run(launcher.worker(metadata['schema']))
