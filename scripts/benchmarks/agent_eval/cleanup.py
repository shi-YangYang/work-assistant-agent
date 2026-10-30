"""Explicit cleanup of a verified owned schema and its per-trial credentials."""
import subprocess
import sys
from pathlib import Path
from .adapters import environment, AUDIT
from .evidence import read


def cleanup(metadata_path, roots, apply=False):
    path, owner, _ = environment(metadata_path)
    credentials = []
    for root in roots:
        for manifest in Path(root).rglob('metadata.json'):
            value = read(manifest)
            if value.get('schema') != owner['schema'] or value.get('runId') != owner['runId'] or value.get('secretFile') != owner['secretFile']:
                raise ValueError('Cleanup root contains a different environment')
            credential = Path(value['credentialsFile']).resolve()
            if credential != manifest.parent.resolve() / 'credentials.json':
                raise ValueError('Unexpected per-trial credential path')
            credentials.append(credential)
    result = {'schema': owner['schema'], 'perTrialCredentials': [str(p) for p in sorted(set(credentials))], 'apply': apply,
              'services': 'Stop only the separately recorded owned API/worker/browser PIDs; shared Docker services are not stopped by this command'}
    if apply:
        subprocess.run([sys.executable, str(AUDIT.parent / 'environment.py'), 'cleanup', '--metadata', str(path)], check=True)
        for credential in credentials:
            credential.unlink(missing_ok=True)
    return result
