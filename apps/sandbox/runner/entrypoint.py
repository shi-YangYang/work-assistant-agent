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
(root / 'task.py').write_text(request['code'])
os.chdir(root)
result = subprocess.run([sys.executable, '-u', str(root / 'task.py')], env={
    'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': '/work/home', 'TMPDIR': '/work/tmp',
    'MPLCONFIGDIR': '/work/tmp/matplotlib', 'MPLBACKEND': 'Agg', 'LANG': 'C.UTF-8',
    'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'PYTHONUNBUFFERED': '1',
})
sys.exit(result.returncode)
