"""Runner-side validation for untrusted JSON; fixed names, no expression language."""
import json
import math
from .common.paths import filename

NAMES = {'inspect_table', 'export_table', 'create_chart', 'create_document', 'create_slides'}


def obj(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ValueError('工具参数字段无效或缺失')


def text(value, maximum=12000, minimum=0):
    if not isinstance(value, str) or not minimum <= len(value) <= maximum or '\x00' in value:
        raise ValueError('文本为空、过长或含无效字符')


def array(value, maximum, minimum=0):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError('列表长度超出限制')


def integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('数字参数超出范围')


def table(value):
    obj(value, ('columns', 'rows'), ('columns',))
    array(value['columns'], 40, 1)
    for column in value['columns']:
        text(column, 120, 1)
    if len(set(value['columns'])) != len(value['columns']):
        raise ValueError('列名不可重复')
    array(value.get('rows', []), 2000)
    for row in value.get('rows', []):
        array(row, len(value['columns']), len(value['columns']))
        for cell in row:
            if isinstance(cell, str):
                text(cell, 2000)
            elif cell is not None and (type(cell) not in (bool, int, float) or isinstance(cell, (int, float)) and not math.isfinite(cell)):
                raise ValueError('表格只支持文本、有限数字、布尔值和空值')


def source(value):
    obj(value, ('input', 'sheet', 'encoding', 'column_types'), ('input',))
    filename(value['input'])
    text(value.get('sheet', ''), 120)
    if value.get('encoding', 'utf-8-sig') not in ('utf-8-sig', 'utf-8', 'gb18030'):
        raise ValueError('不支持的编码')
    types = value.get('column_types', {})
    if not isinstance(types, dict) or len(types) > 40:
        raise ValueError('列类型参数无效')
    for column, kind in types.items():
        text(column, 120, 1)
        if kind not in ('string', 'number', 'boolean'):
            raise ValueError('不支持的列类型')


def blocks(value, maximum=200):
    array(value, maximum, 1)
    for block in value:
        obj(block, ('type', 'text', 'level', 'items', 'table', 'input', 'caption'), ('type',))
        kind = block['type']
        if ((block.get('text') and kind not in ('heading', 'paragraph')) or (block.get('items') and kind != 'list') or (block.get('caption') and kind != 'image')):
            raise ValueError('内容块包含其他类型的数据，请拆成独立内容块')
        if kind not in ('heading', 'paragraph', 'list', 'table', 'image'):
            raise ValueError('不支持的内容块')
        text(block.get('text', ''), 300 if kind == 'heading' else 12000, 1 if kind in ('heading', 'paragraph') else 0)
        integer(block.get('level', 1), 1, 3)
        text(block.get('caption', ''), 300)
        array(block.get('items', []), 100, 1 if kind == 'list' else 0)
        for item in block.get('items', []):
            text(item, 2000, 1)
        if kind == 'table':
            table(block.get('table'))
        elif 'table' in block:
            raise ValueError('非表格块不可包含表格')
        if kind == 'image':
            filename(block.get('input'))
        elif 'input' in block:
            raise ValueError('非图片块不可包含图片')


def validate(name, args):
    if name not in NAMES:
        raise ValueError('不支持的内置工具，请更新沙盒镜像')
    if len(json.dumps(args, ensure_ascii=False, allow_nan=False).encode()) > 240 * 1024:
        raise ValueError('内置参数超过240 KiB')
    shared = ('data', 'source')
    if name == 'inspect_table':
        obj(args, ('source', 'sample_rows'), ('source',))
        source(args['source'])
        integer(args.get('sample_rows', 8), 0, 20)
    elif name in ('export_table', 'create_chart'):
        extra = ('filename', 'format') if name == 'export_table' else ('filename', 'kind', 'x', 'y', 'title', 'x_label', 'y_label')
        obj(args, (*shared, *extra), ('filename',))
        if (args.get('data') is None) == (args.get('source') is None):
            raise ValueError('data和source必须且只能提供一个')
        table(args['data']) if args.get('data') is not None else source(args['source'])
        filename(args['filename'])
        if name == 'export_table':
            if args.get('format', 'xlsx') not in ('csv', 'xlsx'):
                raise ValueError('不支持的导出格式')
        else:
            if args.get('kind', 'bar') not in ('bar', 'line'):
                raise ValueError('仅支持柱状图和折线图')
            text(args.get('x'), 120, 1)
            array(args.get('y'), 6, 1)
            for column in args['y']:
                text(column, 120, 1)
            if len(set(args['y'])) != len(args['y']):
                raise ValueError('数值列不能重复')
            text(args.get('title', ''), 200)
            for key in ('x_label', 'y_label'):
                text(args.get(key, ''), 120)
    elif name == 'create_document':
        obj(args, ('filename', 'format', 'title', 'blocks'), ('filename', 'title', 'blocks'))
        filename(args['filename']); text(args['title'], 200, 1)
        if args.get('format', 'docx') not in ('docx', 'pdf'):
            raise ValueError('不支持的文档格式')
        blocks(args['blocks'])
    else:
        obj(args, ('filename', 'title', 'pages'), ('filename', 'title', 'pages'))
        filename(args['filename']); text(args['title'], 200, 1)
        array(args['pages'], 40, 1)
        for page in args['pages']:
            obj(page, ('title', 'blocks'), ('title',))
            text(page['title'], 200, 1)
            if page.get('blocks'):
                blocks(page['blocks'], 20)
    return args
