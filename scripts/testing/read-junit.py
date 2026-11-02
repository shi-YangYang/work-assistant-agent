"""Normalize native JUnit without rerunning tests; no third-party dependency."""
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
root = ET.parse(sys.argv[1]).getroot()
cases = []
for case in root.iter('testcase'):
    status = 'failed' if case.find('failure') is not None or case.find('error') is not None else 'skipped' if case.find('skipped') is not None else 'passed'
    cases.append({'id': case.get('classname', '') + ':' + case.get('name', ''), 'status': status})
Path(sys.argv[2]).write_text(json.dumps({'cases': cases, 'complete': True}, indent=2))
