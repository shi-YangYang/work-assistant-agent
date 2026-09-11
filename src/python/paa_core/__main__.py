"""Desktop owns the data root and this process's lifetime."""
import multiprocessing

# PyInstaller must route spawned ASR/resource-tracker processes before any imports or CLI parsing.
if __name__ == '__main__':
    multiprocessing.freeze_support()

import argparse
import sys
from pathlib import Path

if not __package__ and not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--runtime-check', action='store_true')
    parser.add_argument('--model-path', type=Path)
    parser.add_argument('--audio-path', type=Path)
    args = parser.parse_args()
    if args.runtime_check:
        from paa_core.runtime_check import check
        check(args.model_path, args.audio_path)
    else:
        if args.data_dir is None:
            parser.error('--data-dir is required')
        from paa_core.protocol import CoreService, serve
        print('[paa-core] local core started', file=sys.stderr, flush=True)
        serve(sys.stdin.buffer, sys.stdout.buffer, CoreService(args.data_dir))
