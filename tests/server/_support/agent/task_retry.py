"""Shared controlled fixtures extracted from test_task_retry."""
import time
import pytest
from app.tasks.nodes import node_execution
from _support.agent.business_actions import runtime


@pytest.fixture
def fast_nodes(monkeypatch):
    real = node_execution.run
    async def fast(*args, **kwargs):
        clock = [time.time()]
        async def wait(delay):
            clock[0] += delay
        return await real(*args, **{**kwargs, 'jitter': lambda: 0}, clock=lambda: clock[0], wait=wait)
    monkeypatch.setattr(node_execution, 'run', fast)


async def enabled(setup):
    context, sent = await runtime(setup)
    context.node_retry = True
    await node_execution.initialize(context, 'fixed-input')
    return context, sent
