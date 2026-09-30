from html import escape
from .blocks import validate_layout, cell_text
from ..common.paths import output_file, image_path
from ..common.fonts import pdf_font
from ..common.results import result


def create_pdf(*, filename, title, blocks):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle, Image
    from pypdf import PdfReader
    validate_layout(title, blocks)
    font = pdf_font()
    styles = {name: ParagraphStyle(name, fontName=font, fontSize=size, leading=size * 1.55, spaceAfter=8,
                                  wordWrap='CJK', splitLongWords=True, textColor=colors.HexColor('#333333'),
                                  keepWithNext=name.startswith('heading'))
              for name, size in [('title', 22), ('body', 10.5), ('heading1', 16), ('heading2', 13), ('heading3', 11), ('cell', 9)]}
    def paragraph(text, style='body'):
        return Paragraph(escape(text).replace('\n', '<br/>'), styles[style])
    story = [paragraph(title, 'title'), Spacer(1, 10)]
    available = A4[0] - 88
    for block in blocks:
        kind = block['type']
        if kind == 'heading':
            story.append(paragraph(block['text'], 'heading' + str(block.get('level', 1))))
        elif kind == 'paragraph':
            story.append(paragraph(block['text']))
        elif kind == 'list':
            story.extend(paragraph('• ' + item) for item in block['items'])
        elif kind == 'table':
            data = block['table']
            rows = [data['columns'], *data.get('rows', [])]
            table = LongTable([[paragraph(cell_text(cell), 'cell') for cell in row] for row in rows],
                              colWidths=[available / len(data['columns'])] * len(data['columns']), repeatRows=1,
                              splitByRow=1, splitInRow=1)
            table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eeeeee')),
                                       ('GRID', (0, 0), (-1, -1), .4, colors.HexColor('#cccccc')),
                                       ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 7),
                                       ('BOTTOMPADDING', (0, 0), (-1, -1), 7)]))
            story.extend([table, Spacer(1, 10)])
        elif kind == 'image':
            path, width, height = image_path(block['input'])
            scale = min(available / width, 550 / height)
            story.append(Image(str(path), width=width * scale, height=height * scale))
            if block.get('caption'):
                story.append(paragraph(block['caption']))
    with output_file(filename, '.pdf') as path:
        SimpleDocTemplate(str(path), pagesize=A4, rightMargin=44, leftMargin=44, topMargin=42, bottomMargin=42,
                          title=title, author='Noria').build(story)
        pages = len(PdfReader(path).pages)
    return result({'filename': filename, 'pageCount': pages, 'fontEmbedded': True})
