"""Own one disposable browser environment and only its child processes."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.request

root = Path(__file__).resolve().parents[2]
os.chdir(root)
# Direct invocations use the same process-group supervisor as the suite runner.
if os.environ.get('PROJECT_TEST_OWNED_GROUP') != '1':
    os.execvp('node', ['node', str(Path(__file__).resolve().with_name('project-tests.mjs')), '--owned-wrapper', sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])
def interrupted(signum, frame):
    raise KeyboardInterrupt()
signal.signal(signal.SIGTERM, interrupted)
output = Path(os.environ['PROJECT_TEST_OUTPUT']).resolve()
python = sys.executable
manager = 'scripts/company/web-acceptance/environment.py'
metadata = output / 'environment.json'
env = {**os.environ, 'PYTHON_DOTENV_DISABLED': '1'}
if not env.get('DATABASE_TEST_URL'):
    raise RuntimeError('DATABASE_TEST_URL must explicitly identify a local paa_company_test database')

def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]

children, logs = [], []
prepared = False
try:
    ui_port, api_port = port(), port()
    subprocess.run([python, manager, 'prepare', '--suite', 'project', '--purpose', 'web', '--output', str(metadata), '--web-origin', f'http://127.0.0.1:{ui_port}', '--api-url', f'http://127.0.0.1:{api_port}'], env=env, check=True)
    prepared = True
    env.update(PROJECT_TEST_ENVIRONMENT=str(metadata), UI_LAYOUT_RECORDS=str(output / 'records.json'), UI_REPORT_RECORD=str(output / 'report.json'))
    subprocess.run([python, 'tests/e2e/web/fixtures/seed-layout.py', '--metadata', str(metadata), '--output', env['UI_LAYOUT_RECORDS']], env=env, check=True)
    for name, command in [('api', [python, 'scripts/testing/web-runtime.py', str(metadata), 'api']), ('worker', [python, 'scripts/testing/web-runtime.py', str(metadata), 'worker']), ('ui', ['node', 'scripts/testing/web-serve.mjs'])]:
        log = (output / f'{name}.log').open('w'); logs.append(log)
        children.append(subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT))
    for target in [f'http://127.0.0.1:{api_port}/api/v1/health', f'http://127.0.0.1:{ui_port}']:
        deadline = time.monotonic() + 45
        while True:
            if any(p.poll() is not None for p in children):
                raise RuntimeError('Owned service exited; see api.log/ui.log')
            try:
                urllib.request.urlopen(target, timeout=1).close(); break
            except Exception:
                if time.monotonic() >= deadline: raise RuntimeError('Owned service readiness timeout: ' + target)
                time.sleep(.2)
    result = subprocess.run(['node', 'node_modules/@playwright/test/cli.js', 'test', '--config', 'apps/web/playwright.config.ts', *([] if any(arg.startswith('--project') for arg in sys.argv[1:]) else ['--project=chromium']), *sys.argv[1:]], env=env)
    raise SystemExit(result.returncode)
finally:
    for child in children:
        if child.poll() is None: child.terminate()
    for child in children:
        try: child.wait(timeout=10)
        except subprocess.TimeoutExpired: child.kill(); child.wait()
    for log in logs: log.close()
    # Environment cleanup belongs to the supervisor after the whole group exits.
