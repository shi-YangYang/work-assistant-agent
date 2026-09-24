from app.core.errors import problem


def version(record, expected):
    if record.revision != expected:
        problem(409, '内容已在其他页面更新，请读取最新版本后再保存', 'revision_conflict')
