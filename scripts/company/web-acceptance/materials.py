"""Generate frozen synthetic media for opt-in macOS Web acceptance (no real voices)."""
import json
from pathlib import Path
from docx import Document
from pptx import Presentation
from openpyxl import Workbook
from PIL import Image,ImageDraw
base=Path('artifacts/spec044/agent/materials')
base.mkdir(parents=True, exist_ok=True)
(base/'requirements.txt').write_text('客户：星舟书店。需要会员管理、库存查询、每周销售报表。预算20000元，2026年10月16日试运行。缺少现有库存清单和会员导入模板。不得加入在线支付。')
(base/'notes.md').write_text('# 发布计划\n先内部测试，再培训8名员工；负责人未确认。\n')
(base/'limits.json').write_text(json.dumps({'budget':20000,'people':8,'no_online_payment':True}))
(base/'sales.csv').write_text('项目,销售额,退款额\nA,100,10\nB,200,40\n')
d=Document();d.add_heading('验收材料',0);d.add_paragraph('工单A：导入20条数据，其中3条重复。实际新增17条。负责人未提供。');d.save(base/'ticket.docx')
p=Presentation();slide=p.slides.add_slide(p.slide_layouts[1]);slide.shapes.title.text='试运行计划';slide.placeholders[1].text='10月9日测试；10月12日培训；10月16日试运行。';p.save(base/'plan.pptx')
w=Workbook();s=w.active;s.append(['项目','销售额','退款额']);s.append(['A',100,10]);s.append(['B',200,40]);w.save(base/'sales.xlsx')
i=Image.new('RGB',(800,400),'white');ImageDraw.Draw(i).text((50,80),'Inventory: A=12, B=18. Total=30',fill='black',font_size=28);i.save(base/'inventory.png')
# Portable minimal PDF with an embedded simple font via fpdf-independent reportlab fallback.
import subprocess
subprocess.run(['cupsfilter','-m','application/pdf',str(base/'requirements.txt')],stdout=(base/'requirements.pdf').open('wb'),stderr=subprocess.DEVNULL,check=True)

# Fixtures only; a macOS system voice is used, never an employee recording.
subprocess.run(['say', '-v', 'Tingting', '-o', str(base/'audio.aiff'), '明天下午三点，请到会议室B参加培训。'], check=True)
import os
ffmpeg=os.environ.get('PAA_FFMPEG', 'ffmpeg')
subprocess.run([ffmpeg, '-y', '-i', str(base/'audio.aiff'), '-ar', '16000', '-ac', '1', str(base/'audio.wav')], check=True, stderr=subprocess.DEVNULL)
subprocess.run([ffmpeg, '-y', '-stream_loop', '-1', '-i', str(base/'audio.wav'), '-t', '35', '-ar', '16000', '-ac', '1', str(base/'enrollment.wav')], check=True, stderr=subprocess.DEVNULL)
