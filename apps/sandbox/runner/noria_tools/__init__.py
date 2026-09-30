"""Common sandbox operations; imports stay inside the execution container."""
from .contracts import validate

__version__ = '1'


def inspect_table(**arguments):
    from .tables.inspect import inspect_table as run
    return run(**validate('inspect_table', arguments))


def export_table(**arguments):
    from .tables.io import export_table as run
    return run(**validate('export_table', arguments))


def create_chart(**arguments):
    from .charts.render import create_chart as run
    return run(**validate('create_chart', arguments))


def create_document(**arguments):
    values = dict(validate('create_document', arguments))
    format = values.pop('format', 'docx')
    if format == 'pdf':
        from .documents.pdf import create_pdf as run
    else:
        from .documents.word import create_word as run
    return run(**values)


def create_slides(**arguments):
    from .slides.presentation import create_slides as run
    return run(**validate('create_slides', arguments))


TOOLS = {'inspect_table': inspect_table, 'export_table': export_table, 'create_chart': create_chart,
         'create_document': create_document, 'create_slides': create_slides}
