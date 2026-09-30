import json

MAX_RESULT_BYTES = 64 * 1024


def result(data, warnings=None):
    value = {'data': data, 'warnings': warnings or []}
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) > MAX_RESULT_BYTES:
        raise ValueError('结果过大，请减少样本行数或输出到文件')
    return value


def exported(name, **metadata):
    return result({'filename': name, **metadata})
