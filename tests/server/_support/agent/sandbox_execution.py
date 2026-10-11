"""Shared controlled fixtures extracted from test_sandbox_execution."""
import hashlib
import json
from types import SimpleNamespace
import pytest
from app.agent.tools.sandbox.execution import run_python


class ReceiptClient:
    runs = {}
    count = 0
    data = b'a,b\n1,2\n'
    def __init__(self, settings):
        pass
    async def read(self, key):
        return self.runs.get(key)
    async def submit(self, body):
        type(self).count += 1
        key = hashlib.sha256(self.data).hexdigest()
        result = {'state': 'succeeded', 'exitCode': 0, 'stdout': '3', 'stderr': '', 'files': [
            {'id': key, 'sha256': key, 'name': '结果.csv', 'size': len(self.data), 'mimeType': 'text/csv'}]}
        self.runs[body['id']] = result
        return result
    async def file(self, key, metadata):
        return self.data
    async def best_effort(self, operation, key):
        pass


@pytest.fixture
def receipts(monkeypatch):
    ReceiptClient.runs, ReceiptClient.count = {}, 0
    monkeypatch.setattr('app.modules.executions.service.SandboxClient', ReceiptClient)
    return ReceiptClient


async def run(context, **extra):
    return json.loads(await run_python.coroutine(code='print(3)', title='计算结果', runtime=SimpleNamespace(context=context), **extra))
