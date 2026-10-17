"""Clean only the verified disposable Spec073 environment after audit approval."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from environment import cleanup, load_environment

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--metadata', required=True)
args = parser.parse_args()
metadata, _ = load_environment(args.metadata)
if metadata['suite'] != 'spec073' or metadata['purpose'] != 'web':
    raise RuntimeError('Exact owned Spec073 environment required')
processes = [x for x in metadata['processes'] if not x.get('stopped')]
active = []
for process in processes:
    observed = subprocess.run(['ps', '-p', str(process['pid']), '-o', 'command='], text=True, capture_output=True)
    if observed.returncode == 0:
        if observed.stdout.strip() != ' '.join(process['command']):
            raise RuntimeError(f"Process identity mismatch: {process['name']}")
        active.append(process)
for container in metadata.get('containers', []):
    info = json.loads(subprocess.check_output(['docker', 'inspect', container['id']]))[0]
    labels = info['Config']['Labels']
    if labels.get('noria.audit.suite') != 'spec073' or labels.get('noria.audit.run') != metadata['runId']:
        raise RuntimeError('Container ownership mismatch')
for process in active:
    os.kill(process['pid'], signal.SIGTERM)
for process in active:
    deadline = time.monotonic() + 15
    while subprocess.run(['ps', '-p', str(process['pid'])], stdout=subprocess.DEVNULL).returncode == 0:
        if time.monotonic() > deadline:
            raise RuntimeError('Owned process did not terminate; no force kill attempted')
        time.sleep(.1)
for process in processes:
    process['stopped'] = True
for container in metadata.get('containers', []):
    subprocess.run(['docker', 'rm', '-f', container['id']], check=True, stdout=subprocess.DEVNULL)
    container['removed'] = True
Path(args.metadata).write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
cleanup(args)
