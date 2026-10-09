"""Owned fault fixtures and sequential destructive test orchestration."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / 'scripts/company/web-acceptance'), str(ROOT / 'apps/server')]


def isolated_url(settings):
    from sqlalchemy.engine import make_url
    url = make_url(settings.database_url)
    if url.database != 'paa_company_test' or url.host not in ('127.0.0.1', 'localhost'):
        raise RuntimeError('Faults require the local test database')
    if not re.fullmatch(r'-csearch_path=spec059_[a-z]+_[a-f0-9]{12}', url.query.get('options', '')):
        raise RuntimeError('Faults require an owned Spec 059 schema')
    return url


def evidence(name, value):
    directory = os.getenv('SPEC059_FAULT_EVIDENCE')
    if directory:
        path = Path(directory) / (name + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    from environment import load_environment
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--cases', nargs='+')
    args = parser.parse_args()
    metadata, private = load_environment(args.metadata)
    if metadata['suite'] != 'spec059':
        raise RuntimeError('Refusing another suite environment')
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **private['environment'], 'SPEC044_PROCESS_RECOVERY': '1',
           'SPEC044_SERVER_EVIDENCE': str(output), 'SPEC059_FAULT_EVIDENCE': str(output),
           'SPEC059_FIXED_EVIDENCE': str(output), 'PAA_REPLY_STREAM_REDIS_URL': '',
           'PYTHONPATH': os.pathsep.join([str(Path(__file__).parent), private['environment']['PYTHONPATH']])}
    cases = args.cases or [
        'tests/server/test_agent_audit_faults.py',
        'tests/server/test_full_system_acceptance.py::test_twenty_five_simultaneous_same_key_writes_have_one_receipt_and_one_record',
        'tests/server/test_full_system_acceptance.py::test_concurrent_versioned_edits_accept_exactly_one_and_preserve_winner',
        'tests/server/test_full_system_acceptance.py::test_parallel_message_replays_then_cancels_keep_one_job_and_terminal_fence',
    ]
    command = [sys.executable, '-m', 'pytest', '-q', '-p', 'fixed', '--tb=short', '--junitxml=' + str(output / 'faults.xml'), *cases]
    (output / 'command.json').write_text(json.dumps({'command': command, 'schema': metadata['schema'], 'startedAt': time.time()}, indent=2))
    with (output / 'faults.log').open('w') as log:
        code = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    results = []
    for case in ET.parse(output / 'faults.xml').findall('.//testcase'):
        detail = next((case.find(tag) for tag in ('failure', 'error', 'skipped') if case.find(tag) is not None), None)
        results.append({'id': case.attrib['classname'] + '::' + case.attrib['name'],
                        'status': 'PASS' if detail is None else 'BLOCKED' if detail.tag == 'skipped' else 'FAIL',
                        'seconds': float(case.attrib.get('time', 0)), 'detail': detail.text if detail is not None else None})
    (output / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'exitCode': code, 'counts': {state: sum(row['status'] == state for row in results) for state in ('PASS', 'FAIL', 'BLOCKED')}}))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
