"""Bounded structure/active-content and formula-cache checks, never a text parser."""
import math
import re
from urllib.parse import unquote, urlsplit
import struct
import zipfile
from pathlib import Path
from lxml import etree
from document_parser import ParseFailure, office_entries, office_check
from formats import OLE_MAGIC, header_matches

NS = {'office': 'urn:oasis:names:tc:opendocument:xmlns:office:1.0', 'table': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0', 'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0'}
ACTIVE = '文件包含宏、外部数据或活动嵌入对象，请移除后重新保存'
FORMULA = '表格公式保存结果无法可靠保留，请用 Microsoft Office 或 WPS 另存为 XLSX 后上传'


def xml(raw):
    root = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
    if root.getroottree().docinfo.doctype:
        raise ParseFailure('文档包含不支持的 XML 实体声明')
    return root


def records(data, start=0):
    pos = start
    while pos < len(data):
        if pos + 4 > len(data):
            raise ParseFailure('Office 文件结构不完整，请重新导出')
        kind, size = struct.unpack_from('<HH', data, pos)
        end = pos + 4 + size
        if end > len(data):
            raise ParseFailure('Office 文件结构不完整，请重新导出')
        yield kind, data[pos + 4:end], pos
        pos = end


def biff_string(data):
    if len(data) < 3:
        raise ParseFailure(FORMULA)
    count, flags = struct.unpack_from('<HB', data)
    offset = 3 + (2 if flags & 8 else 0) + (4 if flags & 4 else 0)
    size = count * (2 if flags & 1 else 1)
    if offset + size > len(data):
        raise ParseFailure(FORMULA)
    return data[offset:offset + size].decode('utf-16le' if flags & 1 else 'latin1')


def xls_caches(data):
    sheets, caches = [], {}
    for kind, body, _ in records(data):
        if kind == 0x2f:
            raise ParseFailure('文件已加密，请解密后重新上传')
        if kind in (0xd3, 0x5d) or kind == 0x1ae and body[2:4] not in (b'\x01\x04', b'\x01\x3a'):
            raise ParseFailure(ACTIVE)
        if kind == 0x85:
            if len(body) < 8 or body[5] != 0:  # macro/chart sheets are not worksheets
                raise ParseFailure(ACTIVE)
            sheets.append(struct.unpack_from('<I', body)[0])
    for sheet, offset in enumerate(sheets):
        pending = None
        for kind, body, _ in records(data, offset):
            if kind == 0xa:
                break
            if kind == 6:
                if len(body) < 22:
                    raise ParseFailure(FORMULA)
                row, col = struct.unpack_from('<HH', body)
                key = (sheet, row + 1, col + 1)
                result = body[6:14]
                if result[6:8] != b'\xff\xff':
                    caches[key] = ('n', struct.unpack('<d', result)[0])
                elif result[0] == 0:
                    pending = key
                elif result[0] == 1:
                    caches[key] = ('b', str(int(bool(result[2]))))
                elif result[0] == 2:
                    errors = {0:' #NULL!', 7:'#DIV/0!', 15:'#VALUE!', 23:'#REF!', 29:'#NAME?', 36:'#NUM!', 42:'#N/A'}
                    if result[2] not in errors:
                        raise ParseFailure(FORMULA)
                    caches[key] = ('e', errors[result[2]].strip())
                elif result[0] == 3:
                    caches[key] = ('empty', None)
                else:
                    raise ParseFailure(FORMULA)
            elif kind == 0x207 and pending is not None:
                caches[pending] = ('s', biff_string(body)); pending = None
        if pending is not None:
            raise ParseFailure(FORMULA)
    return caches


def odf_caches(root):
    from datetime import datetime
    from openpyxl.utils.datetime import to_excel
    caches, slots = {}, 0
    def attr(cell, namespace, name, default=None):
        return cell.get('{' + NS[namespace] + '}' + name, default)
    for sheet, table in enumerate(root.findall('.//table:table', NS)):
        row = 0
        for line in table.findall('.//table:table-row', NS):
            repeats = int(attr(line, 'table', 'number-rows-repeated', '1'))
            col = 0
            for cell in line:
                if etree.QName(cell).localname not in ('table-cell', 'covered-table-cell'):
                    continue
                count = int(attr(cell, 'table', 'number-columns-repeated', '1'))
                if repeats < 1 or count < 1:
                    raise ParseFailure(FORMULA)
                # Calc 7.4 writes trailing empty cells/rows up to the sheet's
                # full dimensions. Advance coordinates without expanding or
                # charging those empty placeholders as actual content.
                if attr(cell, 'table', 'formula') or attr(cell, 'office', 'value-type') or len(cell):
                    slots += repeats * count
                    if slots > 500_000:
                        raise ParseFailure('表格展开后过大，请拆分文件')
                if attr(cell, 'table', 'formula'):
                    kind = attr(cell, 'office', 'value-type')
                    if cell.get('{urn:org:documentfoundation:names:experimental:calc:xmlns:calcext:1.0}value-type') == 'error':
                        value = ('e', '\n'.join(''.join(p.itertext()) for p in cell.findall('text:p', NS)))
                    elif kind in ('float', 'currency', 'percentage'):
                        value = ('n', float(attr(cell, 'office', 'value')))
                    elif kind == 'date':
                        value = ('n', to_excel(datetime.fromisoformat(attr(cell, 'office', 'date-value'))))
                    elif kind == 'boolean':
                        saved = attr(cell, 'office', 'boolean-value')
                        if saved not in ('true', 'false', '1', '0'):
                            raise ParseFailure(FORMULA)
                        value = ('b', '1' if saved in ('true', '1') else '0')
                    elif kind == 'string':
                        text = attr(cell, 'office', 'string-value')
                        text = text if text is not None else '\n'.join(''.join(p.itertext()) for p in cell.findall('text:p', NS))
                        value = ('s', text)
                    else:
                        raise ParseFailure(FORMULA)
                    for dr in range(repeats):
                        for dc in range(count):
                            caches[sheet, row + dr + 1, col + dc + 1] = value
                col += count
            row += repeats
    return caches


def ppt_check(data):
    # MS-PPT record headers, recursively bounded; active payloads are never opened.
    pending = [(0, len(data), 0)]
    seen = 0
    while pending:
        pos, end, depth = pending.pop()
        if depth > 64:
            raise ParseFailure('演示文稿结构过深，请重新导出')
        while pos < end:
            if pos + 8 > end:
                raise ParseFailure('演示文稿结构损坏，请重新导出')
            options, kind, size = struct.unpack_from('<HHI', data, pos)
            finish = pos + 8 + size
            seen += 1
            if finish > end or seen > 200000:
                raise ParseFailure('演示文稿结构损坏或过大，请重新导出')
            if kind in (4035, 4044, 4046, 4078, 4091, 4113) or kind == 1024 and (size != 12 or struct.unpack_from('<I', data, pos + 12)[0]):
                raise ParseFailure(ACTIVE)
            if kind == 12052:
                raise ParseFailure('文件已加密，请解密后重新上传')
            if options & 15 == 15:
                pending.append((pos + 8, finish, depth + 1))
            pos = finish


def inspect(path, suffix):
    with Path(path).open('rb') as source:
        head = source.read(8)
    if not header_matches(suffix, head):
        raise ParseFailure('文件结构与扩展名不符，请重新导出')
    if head.startswith(b'{\\rtf'):
        raw = Path(path).read_bytes().lower()
        if any(marker in raw for marker in (b'\\object', b'\\objdata', b'\\field', b'\\datastore')):
            raise ParseFailure(ACTIVE)
        return '.rtf', {}
    if head.startswith(OLE_MAGIC):
        import olefile
        with olefile.OleFileIO(path, raise_defects=olefile.DEFECT_INCORRECT) as ole:
            names = {'/'.join(p).lower() for p in ole.listdir()}
            if any('encryptedpackage' in n or 'encryptioninfo' in n for n in names):
                raise ParseFailure('文件已加密，请解密后重新上传')
            if any(any(word in n for word in ('vba', 'macros', 'objectpool', 'ole10native', 'activex')) for n in names):
                raise ParseFailure(ACTIVE)
            required = {'.doc': 'worddocument', '.xls': 'workbook', '.ppt': 'powerpoint document'}[suffix]
            if required not in names:
                raise ParseFailure('暂不支持此 Office 格式变体，请重新导出')
            raw = ole.openstream(next(p for p in ole.listdir() if '/'.join(p).lower() == required)).read()
            if suffix == '.xls':
                return suffix, xls_caches(raw)
            if suffix == '.ppt':
                ppt_check(raw)
            if suffix == '.doc':
                if len(raw) < 12 or struct.unpack_from('<H', raw, 10)[0] & 0x8100:
                    raise ParseFailure('文件已加密或结构损坏，请解密后重新上传')
                for name in names:
                    stream = ole.openstream(name.split('/')).read().lower()
                    if any(token in stream for text in ('includetext', 'includepicture', 'ddeauto') for token in (text.encode(), text.encode('utf-16le'))):
                        raise ParseFailure(ACTIVE)
            return suffix, {}
    with zipfile.ZipFile(path) as archive:
        entries = office_entries(archive)
        names = {e.filename for e in entries}
        if suffix == '.doc' and 'word/document.xml' in names:
            office_check(path, '.docx')
            return '.docx', {}
        for name in names:
            if name.startswith('/') or '\\' in name or any(part in ('.', '..') for part in name.split('/')):
                raise ParseFailure(ACTIVE)
        for entry in entries:
            if entry.filename.lower().startswith(('basic/', 'scripts/', 'object ')):
                raise ParseFailure(ACTIVE)
            if entry.filename.endswith('.xml'):
                tree = xml(archive.read(entry))
                if tree.xpath('//*[local-name()="encryption-data"]'):
                    raise ParseFailure('文件已加密，请解密后重新上传')
                if tree.xpath('//*[local-name()="script" or local-name()="event-listener" or local-name()="object" or local-name()="object-ole"]'):
                    raise ParseFailure(ACTIVE)
                for node in tree.xpath('//*[@*[local-name()="href"]]'):
                    for key, value in node.attrib.items():
                        if key.endswith('}href') and etree.QName(node).localname != 'a':
                            decoded = unquote(value)
                            reference = urlsplit(decoded)
                            parts = reference.path.split('/')
                            # Auto-loaded resources must be actual members of
                            # this package, never paths relative to its folder.
                            if reference.scheme or reference.netloc or reference.query or '%' in decoded or '\\' in decoded or reference.path.startswith('/') or any(p == '..' for p in parts):
                                raise ParseFailure(ACTIVE)
                            member = '/'.join(p for p in parts if p not in ('', '.'))
                            if member and (member not in names or member.endswith('/')):
                                raise ParseFailure(ACTIVE)
                for node in tree.xpath('//*[@*[local-name()="formula"]]'):
                    for key, value in node.attrib.items():
                        if key.endswith('}formula') and (re.search(r'(?:DDE|WEBSERVICE|FILTERXML)\s*\(', value, re.I) or re.search(r"\[[^\]]*(?:://|#)", value)):
                            raise ParseFailure(ACTIVE)
        expected = {'.odt':'text', '.ods':'spreadsheet', '.odp':'presentation'}[suffix]
        if archive.read('mimetype') != ('application/vnd.oasis.opendocument.' + expected).encode():
            raise ParseFailure('文档格式与扩展名不符，请重新导出')
        return suffix, odf_caches(xml(archive.read('content.xml'))) if suffix == '.ods' else {}


def verify_formula_caches(path, expected):
    """Compare raw serialized caches, including date serials; never recalculate."""
    from openpyxl.utils.cell import coordinate_to_tuple
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(path) as archive:
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            strings = [''.join(item.itertext()) for item in xml(archive.read('xl/sharedStrings.xml'))]
        actual, corrected = {}, {}
        for sheet, name in enumerate(sorted((n for n in archive.namelist() if n.startswith('xl/worksheets/sheet') and n.endswith('.xml')), key=lambda n: int(Path(n).stem[5:]))):
            tree = xml(archive.read(name))
            changed = False
            for cell in tree.findall('.//s:c', ns):
                if cell.find('s:f', ns) is None:
                    continue
                row, col = coordinate_to_tuple(cell.get('r'))
                value = cell.find('s:v', ns)
                raw = value.text if value is not None else None
                kind = cell.get('t', 'n')
                if raw is None:
                    result = ('empty', None)
                elif kind == 'n':
                    result = ('n', float(raw))
                elif kind == 's':
                    result = ('s', strings[int(raw)])
                else:
                    result = ('s' if kind == 'str' else kind, raw)
                key = (sheet, row, col)
                # Calc serializes boolean formula caches as numeric 0/1. Preserve
                # their verified original type, without changing/recomputing a value.
                if expected.get(key, ('',))[0] == 'b' and result == ('n', float(expected[key][1])):
                    cell.set('t', 'b'); result = ('b', expected[key][1]); changed = True
                elif expected.get(key, ('',))[0] == 'n' and expected[key][1] in (0, 1) and result == ('b', str(int(expected[key][1]))):
                    # Older Calc ODF exports can store boolean formulas as
                    # numeric 0/1, then write XLSX booleans. Keep the verified
                    # source type in this direction as well; never infer it
                    # from the formula or its displayed text.
                    cell.set('t', 'n'); result = expected[key]; changed = True
                actual[key] = result
            if changed:
                corrected[name] = etree.tostring(tree, encoding='UTF-8', xml_declaration=True)
        if set(expected) != set(actual):
            raise ParseFailure(FORMULA)
        for key, (kind, value) in expected.items():
            other_kind, other = actual[key]
            if kind != other_kind or (not math.isfinite(value) or not math.isfinite(other) or not math.isclose(value, other, rel_tol=1e-12, abs_tol=1e-12) if kind == 'n' else value != other):
                raise ParseFailure('表格公式结果在转换时发生变化，请用 Microsoft Office 或 WPS 另存为 XLSX 后上传')

    if corrected:
        replacement = Path(path).with_suffix('.verified')
        with zipfile.ZipFile(path) as source, zipfile.ZipFile(replacement, 'w', zipfile.ZIP_DEFLATED) as target:
            for entry in source.infolist():
                target.writestr(entry, corrected.get(entry.filename, source.read(entry)))
        replacement.replace(path)
