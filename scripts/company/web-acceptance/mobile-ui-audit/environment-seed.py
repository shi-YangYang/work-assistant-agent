"""Declare synthetic UI records only after verifying the owned acceptance schema."""
import argparse
import asyncio
from datetime import date, timedelta
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'scripts/company/web-acceptance'))
from environment import load_environment


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--roles', nargs='+', choices=('admin', 'employee', 'peer'), default=['admin', 'employee'])
    args = parser.parse_args()
    metadata, private = load_environment(args.metadata)
    if metadata['purpose'] != 'web' or metadata['suite'] != 'spec073':
        raise RuntimeError('Only an owned browser acceptance environment is allowed')
    output = Path(args.output)
    if output.exists():
        raise RuntimeError('Do not overwrite original fixture evidence')
    os.environ.update(private['environment'])
    sys.path.insert(0, str(ROOT / 'apps/server'))
    from app.core.config import Settings
    from app.db import registry
    from app.db.session import database
    from app.modules.work.models import WorkItem, WorkRevision
    from app.modules.conversations.models import Conversation
    from app.modules.messages.models import Message
    from app.modules.reports.models import Report, ReportRevision
    from app.modules.model_services.models import ModelUsage
    engine, sessions = database(Settings())
    markdown = '# 合成验收资料\n\n用于检查长文、代码和表格显示，不代表真实业务。\n\n| 工作 | 结果 |\n| --- | --- |\n| 桌面与手机 | 可读 |\n\n```python\nprint("synthetic layout fixture")\n```\n\n' + '\n\n'.join(f'## 第 {n} 节\n\n核对布局、滚动和内容可读性。' for n in range(1, 12))
    records = {}
    try:
        async with sessions.begin() as db:
            for role in args.roles:
                member = private['accounts'][role]
                owned = dict(company_id=member['companyId'], owner_id=member['id'])
                content = {'title': '界面验收长标题：工作进展与跨设备协作的可读性核对', 'body': {'type': 'doc', 'version': 1, 'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': paragraph}]} for paragraph in markdown.split('\n\n')]} , 'summary': '合成资料，仅用于 UI 检查', 'status': 'in_progress', 'blocker': '', 'nextStep': '记录观察结果'}
                work = WorkItem(**owned, title=content['title'], content=content, revision=2, origin='manual')
                conversation = Conversation(**owned, title='Markdown 与滚动检查')
                db.add_all([work, conversation])
                await db.flush()
                for revision in (1, 2):
                    db.add(WorkRevision(**owned, work_id=work.id, revision=revision, content=content, source_ids=[]))
                message = Message(**owned, conversation_id=conversation.id, text='请展示合成排版资料', reply=markdown)
                db.add(message)
                await db.flush()
                result = {'work': work.id, 'conversation': conversation.id, 'message': message.id}
                for kind, period in [('weekly', date.today() - timedelta(days=date.today().weekday())), ('draft', date.today() - timedelta(days=date.today().weekday()+7)), ('workflow', date.today() - timedelta(days=date.today().weekday()+14))]:
                    content_report = {'completed': '核对需求与界面布局', 'ongoing': '记录跨设备结果', 'blockers': '暂无阻碍', 'next': '完成验收'}
                    report = Report(**owned, kind='weekly', period=str(period), period_end=str(period + timedelta(days=6)), timezone='Asia/Shanghai', content=content_report, source_ids=[], published_revision=1 if kind == 'weekly' else 0)
                    db.add(report)
                    await db.flush()
                    db.add(ReportRevision(**owned, report_id=report.id, revision=1, content=content_report, source_ids=[]))
                    result[kind] = report.id
                db.add(ModelUsage(**owned, status='succeeded', kind='chat', service_name='合成 UI 服务', model_name='synthetic-layout', input_tokens=100, output_tokens=30, actual_input_tokens=100, actual_output_tokens=30, elapsed_ms=220))
                records[role] = result
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(records, indent=2) + '\n')
        if 'employee' in records:
            (output.parent / 'report.json').write_text(json.dumps({'id': records['employee']['workflow']}) + '\n')
        print('Declared synthetic UI fixtures created after ownership verification')
    finally:
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
