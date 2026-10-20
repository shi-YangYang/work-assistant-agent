"""Deterministic, synthetic document facts for Spec072 accuracy/latency probes.

Facts live in content, never filenames, document metadata or user prompts. The
manifest is a grading oracle consumed only by the benchmark process, not agents.
"""
import hashlib
import io
import json
from pathlib import Path


def _bytes(save):
    stream = io.BytesIO()
    save(stream)
    return stream.getvalue()


def _font(size):
    from PIL import ImageFont
    for name in ('/System/Library/Fonts/Supplemental/Arial.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        if Path(name).exists():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default(size=size)


def visual_panel(kind='chart'):
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (1000, 720), 'white')
    draw = ImageDraw.Draw(image)
    draw.text((40, 24), 'Inspection card', fill='black', font=_font(36))
    draw.text((40, 85), 'Reference: R7K9Q2', fill='black', font=_font(32))
    if kind == 'flow':
        for x, label, color in ((50, 'Intake', '#cadfed'), (370, 'Review', '#f8dea1'), (690, 'Release', '#c6e6ce')):
            draw.rounded_rectangle((x, 240, x + 250, 390), 20, fill=color, outline='#333333', width=3)
            draw.text((x + 25, 290), label, fill='black', font=_font(35))
        for x in (310, 630):
            draw.line((x, 315, x + 50, 315), fill='#333333', width=5)
            draw.polygon(((x + 50, 315), (x + 35, 302), (x + 35, 328)), fill='#333333')
        draw.text((80, 470), 'Rejected review returns to Intake.', fill='black', font=_font(30))
    else:
        for x, label, value, color in ((130, 'A', 23, '#d45757'), (420, 'B', 33, '#527dba'), (710, 'C', 39, '#67975d')):
            height = value * 9
            draw.rectangle((x, 590 - height, x + 150, 590), fill=color)
            draw.text((x + 30, 600), label, fill='black', font=_font(34))
            draw.text((x + 30, 540 - height), str(value), fill='black', font=_font(32))
    return _bytes(lambda stream: image.save(stream, 'PNG'))


def fixture_values():
    from docx import Document
    from docx.shared import Inches as WordInches
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference
    from openpyxl.drawing.image import Image as SheetImage
    from pptx import Presentation
    from pptx.util import Inches
    from PIL import Image
    from _support.materials.document_samples import pdf_bytes

    body = 'Batch: L8N4V6\nApproved amount: 7319.25\nDelivery date: 2026-11-23\nCondition: payment only after inspection\n'
    files = {'brief.txt': body.encode(), 'settings.py': b'BATCH = "L8N4V6"\nAMOUNT = 7319.25\nDELIVERY = "2026-11-23"\nPAYMENT_REQUIRES_INSPECTION = True\n'}
    word = Document()
    for line in body.splitlines():
        word.add_paragraph(line)
    files['brief.docx'] = _bytes(word.save)
    files['brief.pdf'] = pdf_bytes((body.replace('\n', '; '),))
    book = Workbook()
    sheet = book.active
    sheet.title = 'Orders'
    for row in (('Batch', 'Amount', 'Delivery', 'Condition'), ('L8N4V6', 7319.25, '2026-11-23', 'payment only after inspection')):
        sheet.append(row)
    files['orders.xlsx'] = _bytes(book.save)
    long_text = ['Document opening marker: A3F8D2.']
    long_text.extend(f'Record {index:04d}: Routine process note; verify approval and retain source documents. ' + 'No special exception. ' * 3 for index in range(2600))
    long_text[1301] = 'Middle review marker: C6H2M9; internal checkpoint only.'
    long_text.append('Final amendment: Z9P4T7; permitted quantity is 6842; prepayment is forbidden.')
    files['records.txt'] = ('\n'.join(long_text) + '\n').encode()
    long_word = Document()
    for paragraph in long_text:
        long_word.add_paragraph(paragraph)
    files['records.docx'] = _bytes(long_word.save)
    files['pages.pdf'] = pdf_bytes(tuple(f'Page {i}: ordinary reference material.' if i != 105 else 'Final appendix: Z9P4T7; permitted quantity 6842; prepayment forbidden.' for i in range(1, 106)))
    deck = Presentation()
    for i in range(1, 106):
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.shapes.add_textbox(Inches(.5), Inches(.5), Inches(9), Inches(1.5)).text = f'Page {i}: ordinary material.' if i != 105 else 'Final appendix: Z9P4T7; permitted quantity 6842; prepayment forbidden.'
    files['pages.pptx'] = _bytes(deck.save)
    chart = visual_panel()
    flow = visual_panel('flow')
    mixed_word = Document()
    mixed_word.add_paragraph('Department: North operations. The inspection evidence is shown below.')
    mixed_word.add_picture(io.BytesIO(chart), width=WordInches(6))
    mixed_word.add_paragraph('Text condition: figures are sample counts, not currency.')
    files['inspection.docx'] = _bytes(mixed_word.save)
    mixed_deck = Presentation()
    slide = mixed_deck.slides.add_slide(mixed_deck.slide_layouts[6])
    slide.shapes.add_picture(io.BytesIO(flow), Inches(.3), Inches(.3), width=Inches(9.3))
    slide.notes_slide.notes_text_frame.text = 'Reviewer must retain evidence for 47 days.'
    files['workflow.pptx'] = _bytes(mixed_deck.save)
    scan = Image.open(io.BytesIO(chart))
    files['scan.pdf'] = _bytes(lambda stream: scan.save(stream, 'PDF', resolution=100))
    files['clauses.pdf'] = pdf_bytes(('Required clause: ALPHA, submit proposal.', 'Required clause: BETA, inspect samples.', 'Required clause: GAMMA, approve budget.', 'Required clause: DELTA, keep invoice.', 'Required clause: EPSILON, archive originals.', 'Required clause: ZETA, retain for 47 days.'))
    full_book = Workbook()
    data = full_book.active
    data.title = 'Measurements'
    for row in (('Group', 'Count'), ('A', 23), ('B', 33), ('C', 39)):
        data.append(row)
    bars = BarChart()
    bars.add_data(Reference(data, min_col=2, min_row=1, max_row=4), titles_from_data=True)
    bars.set_categories(Reference(data, min_col=1, min_row=2, max_row=4))
    data.add_chart(bars, 'D2')
    data.add_image(SheetImage(io.BytesIO(chart)), 'D18')
    files['measurements.xlsx'] = _bytes(full_book.save)
    sparse = Workbook()
    sparse.active['A1'] = 'Sparse register'
    sparse.active['B22050'] = 'Z9P4T7'
    sparse.active['C22050'] = 6842
    files['register.xlsx'] = _bytes(sparse.save)
    return files


def cases():
    ordinary = '请从附件给出批次编号、批准金额和交付日期，并说明付款前必须满足什么条件。简洁回答，不需要写入工作或生成文件。'
    facts = {'batch': ['L8N4V6'], 'amount': ['7319.25', '7,319.25'], 'date': ['2026-11-23', '2026年11月23日', '11月23日'], 'condition': ['验收', '检验', '检查', 'inspection']}
    visual = {'reference': ['R7K9Q2'], 'highest_group': ['C'], 'highest_count': ['39']}
    tail = {'marker': ['Z9P4T7'], 'quantity': ['6842', '6,842'], 'condition': ['禁止预付', '不得预付', '不能预付', '不允许预付', '不预付', '预付款禁止', 'prepayment']}
    return {
        'none': {'files': [], 'prompt': '计算 17 加 26，直接告诉我结果即可。', 'facts': {'sum': ['43']}, 'group': 'ordinary'},
        'text_code': {'files': ['brief.txt', 'settings.py'], 'prompt': ordinary, 'facts': facts, 'group': 'ordinary'},
        'office_pdf': {'files': ['brief.docx', 'brief.pdf'], 'prompt': ordinary, 'facts': facts, 'group': 'ordinary'},
        'table': {'files': ['orders.xlsx'], 'prompt': ordinary, 'facts': facts, 'group': 'ordinary'},
        'repeat': {'files': ['brief.docx', 'brief.docx'], 'prompt': ordinary, 'followup': '再确认一下刚才附件里的付款前提，顺便重复批次、金额和交付日期。', 'facts': facts, 'group': 'ordinary'},
        'tail_text': {'files': ['records.txt'], 'prompt': '请查看文件最后的修订条款，给出修订标记、允许数量和预付款限制。', 'facts': tail, 'group': 'new'},
        'tail_word': {'files': ['records.docx'], 'prompt': '请查看文件最后的修订条款，给出修订标记、允许数量和预付款限制。', 'facts': tail, 'group': 'new'},
        'tail_pdf': {'files': ['pages.pdf'], 'prompt': '请读取最后一页附录，给出附录标记、允许数量和预付款限制。', 'facts': tail, 'group': 'new'},
        'tail_ppt': {'files': ['pages.pptx'], 'prompt': '请读取最后一张幻灯片，给出附录标记、允许数量和预付款限制。', 'facts': tail, 'group': 'new'},
        'mixed_word': {'files': ['inspection.docx'], 'prompt': '请结合文档正文和图里的信息，给出负责部门、图中 Reference 编号、数量最高的组及数量。这些数量的单位是什么？', 'facts': {**visual, 'department': ['North', '北'], 'unit': ['样本', 'sample']}, 'group': 'new'},
        'flow_ppt': {'files': ['workflow.pptx'], 'prompt': '请读取流程图和演讲备注：写出三个阶段的顺序、审核被拒后回到哪一步，以及证据保留多少天。', 'facts': {'intake': ['Intake', '接收', '受理', '录入'], 'review': ['Review', '审核', '审查'], 'release': ['Release', '发布', '放行'], 'return': ['退回', '返回', '回到', '回退', 'returns'], 'retention': ['47']}, 'group': 'new'},
        'scan_pdf': {'files': ['scan.pdf'], 'prompt': '请读取扫描件中的 Reference 编号，以及柱状图中数量最高的组和数量。', 'facts': visual, 'group': 'new'},
        'full_clauses': {'files': ['clauses.pdf'], 'prompt': '请逐页完整列出文件中全部 Required clause 名称，并给出最后一项的保留天数，不要漏掉任何页。', 'facts': {**{word: [word] for word in ('ALPHA', 'BETA', 'GAMMA', 'DELTA', 'EPSILON', 'ZETA')}, 'retention': ['47']}, 'group': 'new'},
        'chart_table': {'files': ['measurements.xlsx'], 'prompt': '请读取工作簿：给出 A、B、C 三组总数、最高组与数量，并读出下方图片里的 Reference 编号。', 'facts': {**visual, 'total': ['95']}, 'group': 'new'},
        'tail_table': {'files': ['register.xlsx'], 'prompt': '请找到表格中最后一条有内容的记录，给出标记和数量。', 'facts': {'marker': ['Z9P4T7'], 'quantity': ['6842', '6,842']}, 'group': 'new'},
    }


def freeze(directory):
    directory = Path(directory)
    if directory.exists() and any(directory.iterdir()):
        raise ValueError('Refusing to replace frozen fixtures')
    directory.mkdir(parents=True, exist_ok=True)
    metadata = {}
    for name, data in fixture_values().items():
        (directory / name).write_bytes(data)
        metadata[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    (directory / 'manifest.json').write_text(json.dumps({'revision': 2, 'files': metadata, 'cases': cases()}, ensure_ascii=False, indent=2) + '\n')
    return metadata
