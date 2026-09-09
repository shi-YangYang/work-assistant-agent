"""Run with python -m paa_core or as a script from the desktop client."""

import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from paa_core.protocol import serve  # noqa: E402

if __name__ == "__main__":
    print("[paa-core] local core started", file=sys.stderr, flush=True)
    serve(sys.stdin.buffer, sys.stdout.buffer)
