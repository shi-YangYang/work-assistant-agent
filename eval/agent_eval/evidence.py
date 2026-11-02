"""Append-only local evidence; a started slot is never automatically retried."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def fingerprint():
    paths = subprocess.check_output(['git', 'ls-files', '-co', '--exclude-standard', '--', 'apps', 'packages', 'scripts', 'eval', 'tests/server/_support', '*lock*'], cwd=ROOT, text=True).splitlines()
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sorted(set(paths)) if (ROOT / p).is_file()}


def seal(value):
    return {**value, 'sha256': digest(value)}


def verify(value):
    body = {k: v for k, v in value.items() if k != 'sha256'}
    if value.get('sha256') != digest(body):
        raise ValueError('Frozen evidence fingerprint mismatch')
    return value


def grader_source():
    paths = list(BASE.glob('*.py')) + [ROOT / 'eval/support/agent/agent_eval_grading.py']
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def verify_files(result, directory, required=()):
    if result and 'browser' in required and not any(name.endswith('.png') for name in result.get('evidenceFiles', {})):
        raise ValueError('Required browser screenshots have no immutable file manifest')
    for row in (result or {}).get('turns', []):
        for file in row.get('files', []):
            path = Path(file['path']).resolve()
            if not path.is_relative_to(directory.resolve()) or not path.is_file() or not file.get('sha256') or hashlib.sha256(path.read_bytes()).hexdigest() != file['sha256']:
                raise ValueError('Missing, changed or unbound download: ' + str(path))
    for name, expected in (result or {}).get('evidenceFiles', {}).items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory.resolve()) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Missing or changed evidence file: ' + name)
    return result
