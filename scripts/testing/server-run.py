"""Run existing server contracts in an owned schema, never the database public schema."""
import os
import signal
from pathlib import Path
import subprocess
import sys
# Direct invocations use the same process-group supervisor as the suite runner.
if os.environ.get('PROJECT_TEST_OWNED_GROUP') != '1':
    os.execvp('node', ['node', str(Path(__file__).resolve().with_name('project-tests.mjs')), '--owned-wrapper', sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])
def interrupted(signum, frame):
    raise KeyboardInterrupt()
signal.signal(signal.SIGTERM, interrupted)
output = Path(os.environ['PROJECT_TEST_OUTPUT']).resolve()
metadata = output / 'environment.json'
python = sys.executable
manager = 'scripts/company/web-acceptance/environment.py'
subprocess.run([python, manager, 'prepare', '--suite', 'project', '--purpose', 'baseline', '--output', str(metadata)], check=True)
try:
    raise SystemExit(subprocess.run([python, manager, 'exec', '--metadata', str(metadata), '--', python, '-m', 'pytest', *sys.argv[1:], '--junitxml=' + str(output / 'results.xml')]).returncode)
finally:
    pass  # Supervisor reclaims the entire group before environment cleanup.
