from collections import Counter
from .io import read_table
from ..common.results import result, MAX_RESULT_BYTES
import json


def inspect_table(*, source, sample_rows=8):
    columns, rows, warnings = read_table(source=source)
    types = {str: 'string', int: 'number', float: 'number', bool: 'boolean', type(None): 'null'}
    fields = []
    for index, column in enumerate(columns):
        values = [row[index] for row in rows]
        fields.append({'name': column, 'types': dict(Counter(types[type(value)] for value in values)),
                       'missing': sum(value is None or value == '' for value in values)})
    duplicates = len(rows) - len({tuple((type(cell).__name__, cell) for cell in row) for row in rows})
    sample = rows[:sample_rows]
    data = {'rowCount': len(rows), 'columns': fields, 'duplicateRows': duplicates,
            'sample': sample, 'sampleTruncated': len(rows) > len(sample)}
    while sample and len(json.dumps({'data': data, 'warnings': warnings}, ensure_ascii=False).encode()) > MAX_RESULT_BYTES:
        sample.pop(); data['sampleTruncated'] = True
    return result(data, warnings)
