"""Collect notices from the locked wheels without including development or user data."""
import importlib.metadata
import json
import re
import sys
import sysconfig
from pathlib import Path

root = Path(__file__).resolve().parent.parent
python_license_candidates = (
    Path(sysconfig.get_path('stdlib')) / 'LICENSE.txt',
    Path(sys.base_prefix) / 'LICENSE.txt',
    Path(sys.base_exec_prefix) / 'LICENSE.txt',
)
python_license = next(
    (path for path in python_license_candidates if path.is_file() and path.stat().st_size > 0),
    None,
)
if python_license is None:
    raise FileNotFoundError(
        'Python runtime license not found; checked: '
        + ', '.join(str(path) for path in python_license_candidates)
    )
output = root / 'dist/core/paa-core/licenses'
output.mkdir(parents=True, exist_ok=True)
# Wheels without notices: upstream release-tag LICENSE files stored in scripts/licenses.
# github.com/OpenNMT/CTranslate2 v4.8.2; google/flatbuffers v25.12.19; huggingface/tokenizers v0.23.2.
manifest = []
for requirement in (root / 'requirements.lock').read_text().splitlines():
    if not requirement or requirement.startswith('#'): continue
    name, version = requirement.split(';')[0].strip().split('==')
    if ';' in requirement and 'win32' in requirement and sys.platform != 'win32': continue
    distribution = importlib.metadata.distribution(name)
    if distribution.version != version: raise RuntimeError(f'Runtime lock mismatch: {name}')
    notices = []
    for file in distribution.files or []:
        if not re.search(r'(?i)(license|copying|notice|copyright)', str(file)): continue
        source = Path(distribution.locate_file(file))
        if not source.is_file() or source.stat().st_size > 2_000_000: continue
        target = output / name / Path(*[part for part in file.parts if part not in ('.', '..')])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        notices.append(str(target.relative_to(output)))
    fallback = root / 'scripts/licenses' / f'{name}-LICENSE'
    if not notices and fallback.exists():
        target = output / name / 'LICENSE'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(fallback.read_bytes())
        notices.append(str(target.relative_to(output)))
    manifest.append({'name': name, 'version': version, 'license': distribution.metadata.get('License-Expression') or distribution.metadata.get('License'), 'notices': notices})
(output / 'Python-LICENSE.txt').write_bytes(python_license.read_bytes())
(output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8')
