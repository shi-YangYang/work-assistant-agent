"""Explicit, bounded local contract suite. Never collected by default CI."""
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from .evidence import ROOT, BASE, read, write, seal, fingerprint


def run(output, selected=None):
    output = Path(output)
    cases = read(BASE / 'diagnostics.json')['cases']
    if selected:
        cases = [c for c in cases if c['id'] in selected]
    source_files = sorted({c['node'].split('::')[0] for c in cases if not c.get('command')})
    hashes = {name: __import__('hashlib').sha256((ROOT / name).read_bytes()).hexdigest() for name in source_files}
    write(output / 'manifest.json', seal({'testSource': hashes, 'execution': 'contract/replay', 'source': fingerprint(), 'cases': cases, 'providerCalls': 0}))
    results = []
    for case in cases:
        xml = output.resolve() / (case['id'] + '.xml')
        command = case.get('command') or [sys.executable, '-m', 'pytest', '-q', case['node'], '--junitxml=' + str(xml)]
        try:
            process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
            (output / (case['id'] + '.log')).write_text(process.stdout + process.stderr)
            tests = list(ET.parse(xml).getroot().iter('testcase')) if xml.exists() else []
            status = 'PASS' if case.get('command') and process.returncode == 0 else 'PASS' if process.returncode == 0 and tests and not any(t.find('skipped') is not None for t in tests) else 'FAIL' if any(t.find('failure') is not None for t in tests) else 'INCOMPLETE'
            results.append({**case, 'status': status, 'command': command, 'returncode': process.returncode, 'tests': len(tests), 'evidence': str(xml), 'layer': 'deterministic-contract; no model understanding claim'})
        except subprocess.TimeoutExpired:
            results.append({**case, 'status': 'INCOMPLETE', 'reason': 'bounded contract timeout'})
    write(output / 'result.json', seal({'checks': results, 'providerCalls': 0}))
    return results
