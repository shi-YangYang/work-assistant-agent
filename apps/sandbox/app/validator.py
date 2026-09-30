"""Fixed bounded decoder, not a user-code interpreter. No inherited credentials."""
import os
import resource
import sys

resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
# macOS restricts virtual memory differently; the production Linux control
# container enforces both this per-decoder cap and its outer memory budget.
if sys.platform == 'linux':
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    if os.geteuid() == 0:
        os.setgroups([])
        os.setgid(65534)
        os.setuid(65534)

from .files import validate
from .schemas import MAX_OUTPUT_BYTES

try:
    data = sys.stdin.buffer.read(MAX_OUTPUT_BYTES + 1)
    if len(data) > MAX_OUTPUT_BYTES:
        raise ValueError('File too large')
    validate(data, sys.argv[1])
except Exception as error:
    sys.stderr.write(str(error)[:240])
    raise SystemExit(1)
