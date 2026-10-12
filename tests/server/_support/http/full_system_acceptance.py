"""Shared controlled fixtures extracted from test_full_system_acceptance."""
import json
import os
from pathlib import Path


def evidence(name, values):
    directory = os.getenv('SPEC044_SERVER_EVIDENCE')
    if directory:
        target = Path(directory) / (name + '.json')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(values, ensure_ascii=False, indent=2) + '\n')
