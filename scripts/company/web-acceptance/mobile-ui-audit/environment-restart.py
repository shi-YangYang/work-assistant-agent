"""Restart only verified Spec073 processes with its independently owned Redis."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from environment import ROOT, load_environment

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--metadata', required=True)
args = parser.parse_args()
metadata, private = load_environment(args.metadata)
if metadata['suite'] != 'spec073' or metadata['purpose'] != 'web':
    raise RuntimeError('Exact owned Spec073 environment required')
container = next(x for x in metadata['containers'] if x['role'] == 'temporary-reply-stream')
info = json.loads(subprocess.check_output(['docker', 'inspect', container['id']]))[0]
labels = info['Config']['Labels']
if labels.get('noria.audit.suite') != 'spec073' or labels.get('noria.audit.run') != metadata['runId']:
    raise RuntimeError('Redis ownership mismatch')
if info['NetworkSettings']['Ports']['6379/tcp'][0]['HostPort'] != '16383':
    raise RuntimeError('Redis port mismatch')
selected = [x for x in metadata['processes'] if x['name'] in ('api', 'provider', 'worker') and not x.get('stopped')]
for process in selected:
    actual = subprocess.check_output(['ps', '-p', str(process['pid']), '-o', 'command='], text=True).strip()
    if actual != ' '.join(process['command']):
        raise RuntimeError(f"Process identity mismatch: {process['name']}")
for process in selected:
    os.kill(process['pid'], signal.SIGTERM)
for process in selected:
    deadline = time.monotonic() + 10
    while subprocess.run(['ps', '-p', str(process['pid'])], stdout=subprocess.DEVNULL).returncode == 0:
        if time.monotonic() > deadline:
            raise RuntimeError('Owned process did not terminate; no force kill attempted')
        time.sleep(.1)
    process['stopped'] = True
output = Path(args.metadata).resolve().parent
env = {k: v for k, v in os.environ.items() if k.lower() not in ('http_proxy', 'https_proxy', 'all_proxy')}
env.update(private['environment'])
env.update(PAA_REPLY_STREAM_REDIS_URL='redis://127.0.0.1:16383/0', SPEC073_STREAM_REDIS='redis://127.0.0.1:16383/0',
           PAA_REPLY_STREAM_NAMESPACE='spec073:' + metadata['runId'])
for process in selected:
    with (output / (process['name'] + '.log')).open('a') as log:
        child = subprocess.Popen(process['command'], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    metadata['processes'].append({'name': process['name'], 'pid': child.pid, 'command': process['command'], 'streamRedis': container['name']})
Path(args.metadata).write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
deadline = time.monotonic() + 30
while True:
    try:
        client.open(metadata['apiOrigin'] + '/api/v1/auth/me', timeout=2).close()
        break
    except urllib.error.HTTPError as error:
        if error.code == 401:
            break
        raise
    except (OSError, urllib.error.URLError):
        if time.monotonic() >= deadline:
            raise
        time.sleep(.2)
print('Owned API, provider, worker restarted with owned Redis; UI and daily services unchanged')
