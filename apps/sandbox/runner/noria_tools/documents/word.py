from .blocks import validate_layout, cell_text
from ..common.paths import output_file, image_path
from ..common.fonts import FONT_NAME, require_font
from ..common.results import result


def create_word(*, filename, title, blocks):
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    require_font(); validate_layout(title, blocks)
    document = Document()
    section = document.sections[0]
    section.top_margin = section.bottom_margin = Inches(.7)
    section.left_margin = section.right_margin = Inches(.75)
    for style_name in ('Normal', 'Title', 'Heading 1', 'Heading 2', 'Heading 3', 'List Bullet'):
        style = document.styles[style_name]
        style.font.name = FONT_NAME
        style.font.color.rgb = RGBColor.from_string('333333')
        fonts = style.element.get_or_add_rPr().get_or_add_rFonts()
        for key in ('asciiTheme', 'eastAsiaTheme', 'hAnsiTheme', 'cstheme'):
            fonts.attrib.pop(qn('w:' + key), None)
        fonts.set(qn('w:eastAsia'), FONT_NAME)
        paragraph = style.element.get_or_add_pPr()
        border = paragraph.find(qn('w:pBdr'))
        if border is not None:
            paragraph.remove(border)
    document.styles['Normal'].font.size = Pt(11)
    document.styles['Normal'].paragraph_format.space_after = Pt(8)
    document.core_properties.title = title
    document.add_heading(title, 0)
    for block in blocks:
        kind = block['type']
        if kind == 'heading':
            document.add_heading(block['text'], block.get('level', 1))
        elif kind == 'paragraph':
            document.add_paragraph(block['text'])
        elif kind == 'list':
            for item in block['items']:
                document.add_paragraph(item, style='List Bullet')
        elif kind == 'table':
            data = block['table']
            table = document.add_table(rows=1, cols=len(data['columns']))
            table.style = 'Table Grid'
            for cell, column in zip(table.rows[0].cells, data['columns'], strict=True):
                cell.text = column
                for run in cell.paragraphs[0].runs:
                    run.bold = True
            repeat = OxmlElement('w:tblHeader'); table.rows[0]._tr.get_or_add_trPr().append(repeat)
            for row in data.get('rows', []):
                for cell, value in zip(table.add_row().cells, row, strict=True):
                    cell.text = cell_text(value)
        elif kind == 'image':
            path, width, height = image_path(block['input'])
            scale = min(6.7 / width, 8.3 / height)
            document.add_picture(str(path), width=Inches(width * scale), height=Inches(height * scale))
            if block.get('caption'):
                document.add_paragraph(block['caption'])
    with output_file(filename, '.docx') as path:
        document.save(path)
        Document(path)
    return result({'filename': filename, 'blockCount': len(blocks), 'editable': True}, ['DOCX使用镜像中文字体；其他设备的分页可能随字体变化，未声明字体嵌入。'])
