"""Seed a declared synthetic draft before running the browser report scenario."""
import argparse
import asyncio
from datetime import date, timedelta
import json
import os
from pathlib import Path

from environment import load_environment


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', required=True)
    parser.add_argument('--period', required=True, type=date.fromisoformat)
    args = parser.parse_args()
    metadata, private = load_environment(args.metadata)
    if metadata['purpose'] != 'web':
        raise RuntimeError('Only the isolated browser environment is supported')
    output = Path(args.metadata).resolve().parent / 'report.json'
    if output.exists():
        raise RuntimeError('Do not overwrite the first report fixture')
    os.environ.update(private['environment'])
    from app.core.config import Settings
    from app.db import registry
    from app.db.session import database
    from app.modules.reports.models import Report, ReportRevision
    engine, sessions = database(Settings())
    member = private['accounts']['employee']
    content = {'completed': '核对了测试需求', 'ongoing': '编写验收脚本',
               'blockers': '等待测试数据', 'next': '补齐恢复流程'}
    try:
        async with sessions.begin() as db:
            report = Report(company_id=member['companyId'], owner_id=member['id'],
                            kind='weekly', period=str(args.period),
                            period_end=str(args.period + timedelta(days=6)),
                            timezone='Asia/Shanghai', content=content, source_ids=[])
            db.add(report)
            await db.flush()
            db.add(ReportRevision(company_id=member['companyId'], owner_id=member['id'],
                                  report_id=report.id, revision=1, content=content, source_ids=[]))
            result = {'id': report.id, 'ownerId': member['id'], 'period': report.period}
        output.write_text(json.dumps(result) + '\n')
        print('Declared synthetic draft created')
    finally:
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
