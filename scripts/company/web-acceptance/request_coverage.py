"""Opt-in pytest observer of real ASGI responses; never records request secrets."""
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

from fastapi import FastAPI
import pytest

ROOT = Path(__file__).resolve().parents[3]
ROWS = defaultdict(lambda: defaultdict(set))
COUNTS = Counter()
BRANCHES = defaultdict(lambda: defaultdict(set))
RESULTS = defaultdict(dict)


@pytest.fixture(scope='session', autouse=True)
def record_api_operations():
    if not os.environ.get('SPEC044_REQUEST_COVERAGE'):
        yield
        return
    inventory = json.loads((ROOT / 'artifacts/spec044/server/inventory.json').read_text())
    operations = {row['id'] for row in inventory['operations']}
    # Static paths win over placeholders when middleware rejects before routing.
    patterns = []
    for row in sorted(inventory['operations'], key=lambda row: row['id'].count('{')):
        method, path = row['id'].split(' ', 1)
        parts = re.split(r'(\{[^}]+\})', path)
        pattern = ''.join('[^/]+' if part.startswith('{') else re.escape(part) for part in parts)
        patterns.append((method, re.compile('^' + pattern + '$'), row['id']))
    original = FastAPI.__call__

    async def observed(app, scope, receive, send):
        if scope['type'] != 'http' or not hasattr(app.state, 'sessions'):
            return await original(app, scope, receive, send)

        async def capture(event):
            if event['type'] == 'http.response.start':
                route = scope.get('route')
                operation = scope['method'] + ' ' + getattr(route, 'path', '')
                if operation not in operations:
                    operation = next((key for method, pattern, key in patterns
                                      if method == scope['method'] and pattern.fullmatch(scope['path'])), None)
                if operation:
                    test = os.environ.get('PYTEST_CURRENT_TEST', '').split(' (')[0]
                    status = str(event['status'])
                    ROWS[operation][status].add(test)
                    COUNTS[operation] += 1
                    parameters = scope.get('path_params', {})
                    choice = parameters.get('choice') or parameters.get('action')
                    if choice in ('confirm', 'cancel', 'ignore'):
                        BRANCHES[operation][choice].add(test)
            await send(event)

        return await original(app, scope, receive, capture)

    FastAPI.__call__ = observed
    yield
    FastAPI.__call__ = original


def pytest_runtest_logreport(report):
    RESULTS[report.nodeid][report.when] = report.outcome


def pytest_sessionfinish(session, exitstatus):
    output = os.environ.get('SPEC044_REQUEST_COVERAGE')
    if not output:
        return
    inventory = json.loads((ROOT / 'artifacts/spec044/server/inventory.json').read_text())
    result = []
    for operation in inventory['operations']:
        key = operation['id']
        statuses = ROWS[key]
        result.append({'operation': key, 'matrix': operation['matrix'],
                       'statuses': {code: sorted(tests) for code, tests in sorted(statuses.items())},
                       'branches': {branch: sorted(tests) for branch, tests in sorted(BRANCHES[key].items())},
                       'requests': COUNTS[key], 'executed': bool(statuses)})
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({'exitstatus': exitstatus,
        'note': 'Actual application ASGI responses, including streams. Execution is evidence to review alongside assertions, not proof of every branch or correctness. Provider MockTransport requests are excluded.',
        'operations': result, 'tests': dict(RESULTS)}, ensure_ascii=False, indent=2) + '\n')
