"""Executed inside the isolated container only. No credentials or API access."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys

request = json.load(sys.stdin)
root = Path('/work')
for name in ('inputs', 'output', 'tmp', 'home'):
    (root / name).mkdir(exist_ok=True)
for item in request['inputs']:
    (root / 'inputs' / item['name']).write_bytes(base64.b64decode(item['data'], validate=True))
task = request.get('task')
if task is None:
    (root / 'task.py').write_text(request['code'])
os.chdir(root)
command = [sys.executable, '-u', '/runner/builtin.py' if task is not None else str(root / 'task.py')]
result = subprocess.run(command, input=json.dumps(task).encode() if task is not None else None, env={
    'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': '/work/home', 'TMPDIR': '/work/tmp',
    'PYTHONPATH': '/runner', 'MPLCONFIGDIR': '/work/tmp/matplotlib', 'MPLBACKEND': 'Agg', 'LANG': 'C.UTF-8',
    'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'PYTHONUNBUFFERED': '1',
})
sys.exit(result.returncode)
