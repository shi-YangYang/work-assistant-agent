from collections import Counter
from .io import inspection_rows
from ..common.results import result, MAX_RESULT_BYTES
import json


def _sample_indices(rows, nonempty, limit):
    if len(rows) <= limit or limit < 2 or not nonempty:
        return min(len(rows), limit), []
    # Keep the old consecutive-prefix sample, reserving at most two of its
    # slots for boundary content. Source positions, not cell values, deduplicate.
    prefix = limit - min(2, limit - 1)
    boundaries = sorted({nonempty[0], nonempty[-1]} - set(range(prefix)))
    if len(boundaries) > limit - prefix:
        boundaries = boundaries[-(limit - prefix):]
    while True:
        prefix = limit - len(boundaries)
        remaining = [index for index in boundaries if index >= prefix]
        if remaining == boundaries:
            return prefix, boundaries
        boundaries = remaining


def inspect_table(*, source, sample_rows=8):
    columns, rows, warnings, header = inspection_rows(source)
    types = {str: 'string', int: 'number', float: 'number', bool: 'boolean', type(None): 'null'}
    fields = []
    for index, column in enumerate(columns):
        values = [row[index] for row in rows if index < len(row)]
        absent = len(rows) - len(values)
        field = {'name': column} if header else {'position': column, 'absent': absent}
        fields.append({**field, 'types': dict(Counter(types[type(value)] for value in values)),
                       'missing': absent + sum(value is None or value == '' for value in values)})
    duplicates = len(rows) - len({tuple((type(cell).__name__, cell) for cell in row) for row in rows})
    nonempty = [index for index, row in enumerate(rows) if any(value is not None and value != '' for value in row)]
    prefix, boundaries = _sample_indices(rows, nonempty, sample_rows)
    sample, content_samples = [], []
    row_start = 2 if header else 1
    data = {'rowCount': len(rows), 'columns': fields, 'duplicateRows': duplicates,
            'sample': sample, 'sampleStartRow': row_start, 'sampleTruncated': False,
            'contentSamples': content_samples, 'contentSamplesTruncated': False,
            'emptyRows': len(rows) - len(nonempty),
            'firstContentRow': nonempty[0] + row_start if nonempty else None,
            'lastContentRow': nonempty[-1] + row_start if nonempty else None}
    if not header:
        data.update(headerStatus='unavailable', columnCount=len(columns))

    def within_budget():
        return len(json.dumps({'data': data, 'warnings': warnings}, ensure_ascii=False).encode()) <= MAX_RESULT_BYTES

    # Reserve room for informative boundaries first, without shortening cells.
    # A large row is omitted explicitly; it must not hide a smaller tail row.
    for index in boundaries:
        content_samples.append({'rowNumber': index + row_start, 'values': rows[index]})
        if not within_budget():
            content_samples.pop()
    for row in rows[:prefix]:
        sample.append(row)
        if not within_budget():
            sample.pop()
            break
    provided = {*range(len(sample)), *(item['rowNumber'] - row_start for item in content_samples)}
    data['sampleTruncated'] = len(rows) > len(provided)
    data['contentSamplesTruncated'] = bool(nonempty) and not {nonempty[0], nonempty[-1]}.issubset(provided)
    return result(data, warnings)
