"""Shared controlled fixtures extracted from test_work_conflict_refresh."""
from types import SimpleNamespace
from langchain_core.messages import AIMessage


def tool_request(context, name, args, identifier):
    call = {'name': name, 'args': args, 'id': identifier}
    return SimpleNamespace(runtime=SimpleNamespace(context=context), tool_call=call,
                           state={'messages': [AIMessage(id='model:' + identifier, content='', tool_calls=[call])]})
