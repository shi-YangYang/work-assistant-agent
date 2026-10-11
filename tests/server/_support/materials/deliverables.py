"""Shared controlled fixtures extracted from test_deliverables."""
import json
from types import SimpleNamespace
from app.agent.tools.resources.deliverables import read_deliverable, save_deliverable


async def save_plan(context, **params):
    return json.loads(await save_deliverable.coroutine(runtime=SimpleNamespace(context=context), **params))


async def read_plan(context, identifier='', revision=0):
    return json.loads(await read_deliverable.coroutine(runtime=SimpleNamespace(context=context), deliverable_id=identifier, revision=revision))
