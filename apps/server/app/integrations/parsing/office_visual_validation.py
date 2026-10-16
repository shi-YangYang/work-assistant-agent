"""Additional checks before allowing OOXML into the fixed native renderer."""
import zipfile
import re
from lxml import etree
try:
    from .document_parser import ParseFailure
except ImportError:
    from document_parser import ParseFailure


ACTIVE_FIELD = re.compile(r'\b(?:DDE(?:AUTO)?|INCLUDETEXT|INCLUDEPICTURE|LINK|DATABASE|RD)\b|\b(?:WEBSERVICE|FILTERXML)\s*\(', re.I)


def reject_active(instruction):
    if ACTIVE_FIELD.search(instruction):
        raise ParseFailure('文件包含活动字段，未渲染')


def validate(path):
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if '/externalLinks/' in name:
                raise ParseFailure('文件包含外部数据，请移除后重新导出')
            if not name.endswith(('.xml', '.rels')):
                continue
            root = etree.fromstring(archive.read(name), etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
            # A complex Word field may split even the instruction keyword over
            # several runs. Check the combined instruction, never each run alone.
            instructions = []
            for node in root.iter():
                if not isinstance(node.tag, str):
                    continue
                if node.get('TargetMode') == 'External' and not node.get('Type', '').endswith('/hyperlink'):
                    raise ParseFailure('图片部分包含外部资源，未加载')
                kind = etree.QName(node).localname
                if kind == 'instrText':
                    instructions.append(node.text or '')
                elif kind == 'fldChar' and node.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}fldCharType') in ('begin', 'end', 'separate'):
                    reject_active(''.join(instructions))
                    instructions.clear()
                elif kind == 'fldSimple':
                    reject_active(node.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}instr', node.get('instr', '')))
                elif kind == 'f':
                    reject_active(node.text or '')
            reject_active(''.join(instructions))


def select_sheet(path, title):
    with zipfile.ZipFile(path) as source:
        root = etree.fromstring(source.read('xl/workbook.xml'), etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
        sheets = root.findall('{*}sheets/{*}sheet')
        selected = next((sheet for sheet in sheets if sheet.get('name') == title and sheet.get('state', 'visible') == 'visible'), None)
        if selected is None:
            raise ParseFailure('工作表不存在或已隐藏')
        for sheet in sheets:
            sheet.set('state', 'visible' if sheet is selected else 'hidden')
        for view in root.findall('{*}bookViews/{*}workbookView'):
            view.set('activeTab', str(sheets.index(selected)))
        temporary = path.with_suffix('.selected')
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as target:
            for entry in source.infolist():
                target.writestr(entry, etree.tostring(root) if entry.filename == 'xl/workbook.xml' else source.read(entry))
    temporary.replace(path)
