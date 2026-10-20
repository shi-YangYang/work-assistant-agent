import hashlib
import json

from app.modules.executions.output_evidence import PREVIEW_CHARS, file_results


def output(name, data, mime='application/json'):
    file = {'id': 'saved-' + name, 'name': name, 'mimeType': mime, 'sha256': hashlib.sha256(data).hexdigest()}
    return file, (file, data)


def test_generated_numeric_evidence_preserves_actual_values_and_unspecified_units():
    raw = b'{"items":[{"name":"A","net":90},{"name":"B","net":160}],"total":250}'
    file, payload = output('result.json', raw)
    result = file_results([file], [payload])[0]
    assert result['content'].encode() == raw and not result['truncated']
    assert result['fileId'] == file['id'] and result['sha256'] == file['sha256']
    assert result['untrusted'] and json.loads(result['content'])['items'][1]['net'] == 160
    assert 'currency' not in result and 'unit' not in result


def test_output_excerpts_share_a_small_budget_and_do_not_parse_or_execute_content():
    first = output('table.csv', ('列\n' + '甲乙' * 1100).encode(), 'text/csv')
    second = output('large.json', ('["' + '三' * 10000 + '"]').encode())
    image = output('image.png', b'png bytes', 'image/png')
    results = file_results([first[0], image[0], second[0]], [first[1], image[1], second[1]])
    assert len(results) == 2 and sum(len(item['content']) for item in results) == PREVIEW_CHARS
    assert not results[0]['truncated'] and results[1]['truncated']
    assert results[1]['content'].startswith('["三')
    invalid = output('invalid.csv', b'\xffbad', 'text/csv')
    assert file_results([invalid[0]], [invalid[1]]) == []
