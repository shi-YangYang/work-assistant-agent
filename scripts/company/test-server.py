"""Fast server tests plus sandbox protocol tests in separate module namespaces."""
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
paths = sys.argv[1:]
protocol_only = paths == ['--sandbox-protocol']
if not protocol_only:
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', *(paths or ['tests/server'])], cwd=root)
    if result.returncode:
        raise SystemExit(result.returncode)
if not paths or protocol_only:
    # Both apps deliberately use a private top-level app package. Do not load
    # their modules into the same interpreter or require Docker in default CI.
    result = subprocess.run([sys.executable, str(root / 'tests/sandbox/test_protocol.py')], cwd=root,
                            env={**os.environ, 'PYTHONPATH': str(root / 'apps/sandbox')})
    raise SystemExit(result.returncode)
