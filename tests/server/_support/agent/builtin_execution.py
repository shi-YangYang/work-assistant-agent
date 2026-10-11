"""Shared controlled fixtures extracted from test_builtin_execution."""
import copy
import json
from types import SimpleNamespace
import pytest
from app.agent.tools.sandbox.execution import read_execution
from app.agent.tools.sandbox import SANDBOX_TOOLS
from _support.agent.sandbox_execution import ReceiptClient


TOOLS = {tool.name: tool for tool in SANDBOX_TOOLS}


DATA = {'columns': ['编号', '数量'], 'rows': [['001', 3], ['002', 5]]}


@pytest.fixture
def builtin_receipts(monkeypatch):
    class Client(ReceiptClient):
        runs = {}
        count = 0
        bodies = []
        downloads = 0
        state = 'succeeded'
        with_file = False
        structured = {'data': {'rows': 2}, 'warnings': ['固定输入检查结果']}

        async def submit(self, body):
            type(self).bodies.append(copy.deepcopy(body))
            result = await super().submit(body)
            result.update(copy.deepcopy(self.structured), state=self.state)
            if not self.with_file:
                result['files'] = []
            if self.state != 'succeeded':
                result.update(exitCode=1, stderr='ValueError: invalid table data')
            return result

        async def file(self, key, metadata):
            type(self).downloads += 1
            return await super().file(key, metadata)

    monkeypatch.setattr('app.modules.executions.service.SandboxClient', Client)
    return Client


async def invoke(context, name='export_table', **arguments):
    return json.loads(await TOOLS[name].coroutine(runtime=SimpleNamespace(context=context), **arguments))


async def read(context, identifier='', offset=0):
    return json.loads(await read_execution.coroutine(SimpleNamespace(context=context), identifier, offset))
