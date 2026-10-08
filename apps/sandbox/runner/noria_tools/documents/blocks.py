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


def check_page_limit(pages, maximum):
    if pages < 1:
        raise ValueError('文档渲染未产生有效页面，未发布文件')
    if maximum is not None and pages > maximum:
        raise ValueError(f'完整内容按可读字号排版后为{pages}页，超过{maximum}页上限；未发布文件。'
                         '请与用户确认调整篇幅或页数要求，不能省略页限、删除内容或继续缩小字号绕过。')
