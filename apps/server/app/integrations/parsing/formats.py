"""Fixed document routes shared with the upload capability contract."""
import json
from pathlib import Path

_RULES = json.loads((Path(__file__).resolve().parents[5] / 'packages/api-contracts/input-rules.json').read_text())['attachment']
OFFICE_TARGETS = {'.' + source: '.' + target for source, target in _RULES['officeConversion'].items()}
OLE_MAGIC = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'


def header_matches(suffix, header):
    if suffix == '.doc':
        return header.startswith((OLE_MAGIC, b'{\\rtf', b'PK\x03\x04'))
    if suffix in ('.xls', '.ppt'):
        return header.startswith(OLE_MAGIC)
    if suffix == '.rtf':
        return header.startswith(b'{\\rtf')
    if suffix in ('.odt', '.ods', '.odp'):
        return header.startswith(b'PK\x03\x04')
    return True
