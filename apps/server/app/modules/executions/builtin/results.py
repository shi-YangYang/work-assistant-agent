"""Bounded structured results; never treat a truncated JSON string as data."""
import json

MAX_RESULT_BYTES = 64 * 1024


def structured_result(value):
    data, warnings = value.get('data', {}), value.get('warnings', [])
    if not isinstance(data, dict) or not isinstance(warnings, list) or len(warnings) > 40:
        raise ValueError('内置工具返回格式无效')
    if any(not isinstance(item, str) or len(item) > 1000 for item in warnings):
        raise ValueError('内置工具警告格式无效')
    result = {'data': data, 'warnings': warnings}
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > MAX_RESULT_BYTES:
        raise ValueError('内置工具结果超过大小限制')
    return result
