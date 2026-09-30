"""Shared content checks, without interpreting markup or expressions."""
from ..common.paths import image_path


def validate_layout(title, blocks):
    total = len(title)
    for block in blocks:
        total += len(block.get('text', '')) + sum(map(len, block.get('items', [])))
        if block['type'] == 'table':
            table = block['table']
            if len(table['columns']) > 8:
                raise ValueError('文档表格最多8列；宽表请交付电子表格或明确拆分')
            total += sum(len(str(cell)) for row in table.get('rows', []) for cell in row)
        if block['type'] == 'image':
            image_path(block['input'])
    if total > 100000:
        raise ValueError('文档内容超过100000字，请拆成多个文件')


def cell_text(value):
    return '' if value is None else str(value)
