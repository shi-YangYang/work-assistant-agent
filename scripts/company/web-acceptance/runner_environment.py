"""Resolve legacy credentials through their owned manifest before any runner writes."""
import argparse
import json
from pathlib import Path
import re

from environment import load_environment


def manifest_for(state_path):
    state_path = Path(state_path).resolve()
    matches = []
    for candidate in state_path.parent.glob('*.json'):
        if candidate == state_path or candidate.stat().st_size > 2_000_000:
            continue
        try:
            value = json.loads(candidate.read_text())
        except (ValueError, OSError):
            continue
        if isinstance(value, dict) and value.get('credentialsFile') and Path(value['credentialsFile']).resolve() == state_path:
            matches.append(candidate)
    if len(matches) != 1:
        raise RuntimeError('Legacy state requires one adjacent manifest that owns its credentials')
    return matches[0]


def runner_environment(*, metadata_path=None, state_path=None):
    path = Path(metadata_path).resolve() if metadata_path else manifest_for(state_path)
    metadata = json.loads(path.read_text())
    if metadata.get('cleaned'):
        raise RuntimeError('Acceptance environment was already cleaned')
    metadata, _ = load_environment(path)
    credentials = Path(metadata['credentialsFile']).resolve()
    if credentials != path.parent / 'credentials.json':
        raise RuntimeError('Unexpected credentials location')
    if state_path and credentials != Path(state_path).resolve():
        raise RuntimeError('Credentials do not belong to this manifest')
    if credentials.stat().st_mode & 0o077:
        raise RuntimeError('Private credentials required')
    state = json.loads(credentials.read_text())
    if any(state.get(key) != metadata.get(key) for key in ('schema', 'runId', 'origin', 'apiOrigin')):
        raise RuntimeError('Credentials and manifest identity differ')
    if any(not re.fullmatch(r'http://127\.0\.0\.1:[0-9]{1,5}', state[key]) for key in ('origin', 'apiOrigin')):
        raise RuntimeError('Owned local API and browser origins required')
    if state_path and not metadata_path:
        if metadata['purpose'] != 'web' or state['origin'] != 'http://127.0.0.1:5196' or state['apiOrigin'] != 'http://127.0.0.1:8016':
            raise RuntimeError('Legacy entrypoint requires the dedicated browser environment')
    companies = set(metadata['companies'].values())
    for account in state['users'].values():
        if account.get('companyId') not in companies or not all(account.get(key) for key in ('id', 'username', 'password')):
            raise RuntimeError('Synthetic account does not belong to this environment')
    return path, metadata, state


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--metadata')
    source.add_argument('--state')
    args = parser.parse_args()
    path, metadata, _ = runner_environment(metadata_path=args.metadata, state_path=args.state)
    # Browser subprocesses receive paths only; never emit credentials.
    print(json.dumps({'metadataPath': str(path), 'credentialsFile': metadata['credentialsFile']}))
