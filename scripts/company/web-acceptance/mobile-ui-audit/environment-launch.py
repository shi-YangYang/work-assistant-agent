"""Launch only Spec073-owned API/UI processes with disposable storage."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import urllib.request
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from environment import ROOT, load_environment

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--metadata', required=True)
args = parser.parse_args()
metadata, private = load_environment(args.metadata)
if metadata['suite'] != 'spec073' or metadata['purpose'] != 'web':
    raise RuntimeError('Exact owned Spec073 browser environment required')
if metadata['origin'] != 'http://127.0.0.1:5196' or metadata['apiOrigin'] != 'http://127.0.0.1:8016':
    raise RuntimeError('Unexpected dedicated ports')
for port in (8016, 5196):
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1', port)) == 0:
            raise RuntimeError(f'Dedicated port {port} is already in use')
output = Path(args.metadata).resolve().parent
env = {k: v for k, v in os.environ.items() if k.lower() not in ('http_proxy', 'https_proxy', 'all_proxy')}
env.update(private['environment'])
env.update(PAA_REPLY_STREAM_REDIS_URL='', PAA_REPLY_STREAM_NAMESPACE='spec073:' + metadata['runId'],
           SPEC073_ENVIRONMENT=str(Path(args.metadata).resolve()), SPEC073_OUTPUT=str(output))
commands = {
    'api': [str(ROOT / '.venv-server/bin/python'), '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8016'],
    'ui': ['node', 'scripts/company/web-acceptance/mobile-ui-audit/environment-serve.mjs'],
}
for name, command in commands.items():
    with (output / (name + '.log')).open('w') as log:
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    metadata['processes'].append({'name': name, 'pid': child.pid, 'command': command})
Path(args.metadata).write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for origin, path in ((metadata['apiOrigin'], '/api/v1/auth/me'), (metadata['origin'], '/')):
    deadline = time.monotonic() + 40
    while True:
        try:
            client.open(origin + path, timeout=2).close()
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                break
            raise
        except (OSError, urllib.error.URLError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(.25)
print(json.dumps({'origin': metadata['origin'], 'apiOrigin': metadata['apiOrigin'], 'schema': metadata['schema'], 'processes': metadata['processes']}))
