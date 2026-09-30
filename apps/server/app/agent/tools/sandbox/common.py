import json
from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
from app.modules.executions.service import execute
from app.modules.executions.requests import builtin_request


def values(arguments):
    if isinstance(arguments, BaseModel):
        return arguments.model_dump(mode='json', exclude_none=True)
    if isinstance(arguments, dict):
        return {key: values(value) for key, value in arguments.items() if value is not None}
    if isinstance(arguments, list):
        return [values(value) for value in arguments]
    return arguments


async def invoke(runtime, name, arguments, *, title, deliverable_id='', expected_revision=0, step=1):
    try:
        task = builtin_request(name, values(arguments))
        result = await execute(runtime.context, title=title, task=task, identifier=deliverable_id, revision=expected_revision, step=step)
    except HTTPException as error:
        result = {'state': 'failed', 'message': error.detail['message']}
    except ValidationError as error:
        result = {'state': 'failed', 'message': '；'.join('.'.join(map(str, entry['loc'])) + ': ' + entry['msg'] for entry in error.errors(include_input=False)[:5])}
    except ValueError as error:
        result = {'state': 'failed', 'message': str(error)[:1000]}
    return json.dumps(result, ensure_ascii=False)
