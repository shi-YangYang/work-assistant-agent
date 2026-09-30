"""Task snapshots and bindings; authorization stays in prepare_inputs."""
import json
from app.core.digests import digest
from .builtin.schemas import ARGUMENTS

MAX_ARGUMENT_BYTES = 240 * 1024


def builtin_request(name, arguments):
    if name not in ARGUMENTS:
        raise ValueError('不支持的内置工具，请更新执行环境')
    arguments = ARGUMENTS[name].model_validate(arguments).model_dump(mode='json', exclude_none=True)
    if len(json.dumps(arguments, ensure_ascii=False, allow_nan=False).encode()) > MAX_ARGUMENT_BYTES:
        raise ValueError('工具参数超过240 KiB，请通过文件引用传递大表')
    return {'kind': 'builtin', 'name': name, 'version': 1, 'arguments': arguments}


def references_for(task):
    references = []
    def visit(value):
        if isinstance(value, dict):
            if 'input_ref' in value:
                reference = {key: item for key, item in value['input_ref'].items() if item}
                if reference not in references:
                    references.append(reference)
            for key, item in value.items():
                if key != 'input_ref':
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(task['arguments'])
    return references


def bind_inputs(task, references, inputs):
    names = {digest(ref): item['name'] for ref, item in zip(references, inputs, strict=True)}
    def bind(value):
        if isinstance(value, dict):
            result = {key: bind(item) for key, item in value.items() if key != 'input_ref'}
            if 'input_ref' in value:
                reference = {key: item for key, item in value['input_ref'].items() if item}
                result['input'] = names[digest(reference)]
            return result
        if isinstance(value, list):
            return [bind(item) for item in value]
        return value
    return {**task, 'arguments': bind(task['arguments'])}


def execution_key(*, job, code, task, inputs, sources, title, identifier, revision, step):
    # Preserve the exact original Python identity; no added null/version keys.
    identity = {'job': job, 'code': code, 'inputs': inputs, 'sources': sources, 'title': title,
                'target': identifier, 'revision': revision, 'step': step}
    if task is not None:
        del identity['code']
        identity['task'] = task
    return digest(identity)
