"""Run the complete server suite once in an exact owned Spec068 environment."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from environment import ROOT, load_environment


def main(args):
    metadata, private = load_environment(args.metadata)
    if metadata['suite'] != 'spec068' or metadata['purpose'] != 'baseline':
        raise RuntimeError('Exact Spec068 baseline environment required')
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'first-results.json').exists() or (output / 'server.log').exists():
        raise RuntimeError('Refusing to overwrite initial results')
    resource = json.loads(Path(args.resources).read_text())
    env = {key: value for key, value in os.environ.items() if key.lower() not in ('http_proxy', 'https_proxy', 'all_proxy')}
    env.update(private['environment'])
    env.update(PAA_AGENT_FAULT_ENVIRONMENT=str(Path(args.metadata).resolve()),
               PAA_AGENT_FAULT_RESOURCES=str(Path(args.resources).resolve()),
               PAA_REPLY_STREAM_TEST_URL=resource['redisUrl'],
               PAA_REPLY_STREAM_REDIS_URL=resource['redisUrl'],
               PAA_REPLY_STREAM_NAMESPACE='spec068:' + metadata['runId'],
               SPEC059_FIXED_EVIDENCE=str(output), SPEC059_FAULT_EVIDENCE=str(output / 'faults'),
               SPEC044_SERVER_EVIDENCE=str(output / 'faults'), SPEC044_PROCESS_RECOVERY='1',
               ACCEPTANCE_REQUEST_COVERAGE=str(output / 'request-coverage.json'),
               ACCEPTANCE_INVENTORY=str(Path(args.inventory).resolve()),
               PYTHONPATH=os.pathsep.join([str(BASE), str(ROOT / 'eval/web/agent-audit'), str(ROOT / 'tests/server'), str(ROOT / 'tests/server/modules/image_generation'), private['environment']['PYTHONPATH']]))
    command = [str(ROOT / '.venv-server/bin/python'), '-m', 'pytest', '-q', '-p', 'fixed', '-p', 'request_coverage',
               '--tb=short', *(['--import-mode=importlib'] if args.importlib else []), '--junitxml=' + str(output / 'server.xml'), *(json.loads(Path(args.cases).read_text()) if args.cases else ['tests/server'])]
    start = time.monotonic()
    (output / 'command.json').write_text(json.dumps({'command': command, 'schema': metadata['schema'], 'startedAt': time.time()}, indent=2))
    with (output / 'server.log').open('w') as log:
        code = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    rows = []
    for case in ET.parse(output / 'server.xml').findall('.//testcase'):
        detail = next((case.find(tag) for tag in ('failure', 'error', 'skipped') if case.find(tag) is not None), None)
        rows.append({'id': case.attrib['classname'] + '::' + case.attrib['name'],
                     'status': 'PASS' if detail is None else 'BLOCKED' if detail.tag == 'skipped' else 'FAIL',
                     'seconds': float(case.attrib.get('time', 0)),
                     'detail': (detail.text or detail.attrib.get('message')) if detail is not None else None})
    result = {'commit': metadata['commit'], 'exitCode': code, 'seconds': round(time.monotonic() - start, 2),
              'counts': {state: sum(r['status'] == state for r in rows) for state in ('PASS', 'FAIL', 'BLOCKED')}, 'cases': rows}
    (output / 'first-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    # Match the independent protocol namespace once; scoped continuations reuse its result.
    if not args.cases:
        with (output / 'sandbox-protocol.log').open('w') as log:
            protocol = subprocess.run([str(ROOT / '.venv-server/bin/python'), str(ROOT / 'tests/sandbox/test_protocol.py')], cwd=ROOT,
                                  env={**env, 'PYTHONPATH': str(ROOT / 'apps/sandbox')}, stdout=log, stderr=subprocess.STDOUT).returncode
        (output / 'sandbox-protocol-result.json').write_text(json.dumps({'exitCode': protocol}))
    print(json.dumps({k: v for k, v in result.items() if k != 'cases'}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('metadata', 'output', 'resources', 'inventory'):
        parser.add_argument('--' + key, required=True)
    parser.add_argument('--cases', help='JSON list of affected test node IDs; no passed groups rerun')
    parser.add_argument('--importlib', action='store_true', help='Explicit harness-only recovery of duplicate test module names')
    main(parser.parse_args())
