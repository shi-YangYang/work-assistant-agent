"""Desktop owns the data root and this process's lifetime."""
import argparse
import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from paa_core.protocol import CoreService, serve

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, required=True)
    args = parser.parse_args()
    print('[paa-core] local core started', file=sys.stderr, flush=True)
    serve(sys.stdin.buffer, sys.stdout.buffer, CoreService(args.data_dir))
