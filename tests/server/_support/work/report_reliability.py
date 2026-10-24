"""Shared controlled fixtures extracted from test_report_reliability."""
import json
from datetime import datetime, timezone
from langchain_core.messages import AIMessage
from app.db.base import now
from app.modules.reports.service import ensure_report
from app.modules.work.models import WorkItem, WorkRevision


CONTENT = {'completed': '方案初稿已完成', 'ongoing': '等待确认', 'blockers': '', 'next': '继续核对'}


class ReportModel:
    def __init__(self, content=None, callback=None, finish='stop', verdict='{"valid":true}'):
        self.content = json.dumps(CONTENT, ensure_ascii=False) if content is None else content
        self.calls = 0
        self.callback = callback
        self.finish = finish
        self.inputs = []
        self.verdict, self.reviews = verdict, []

    async def ainvoke(self, messages):
        if json.loads(messages[-1].content).get('task') == 'report_fact_review':
            self.reviews.append(messages)
            return AIMessage(content=self.verdict)
        self.calls += 1
        self.inputs.append(messages)
        if self.callback:
            await self.callback()
        return AIMessage(content=self.content, response_metadata={'finish_reason': self.finish})


async def prepared(setup, *, day=None):
    settings, sessions, users, clients = setup
    actor = users['employee']
    instant = now()
    if day:
        instant = datetime.fromisoformat(day).replace(hour=6, tzinfo=timezone.utc)
    async with sessions.begin() as db:
        work = WorkItem(company_id=actor.company_id, owner_id=actor.id, title='方案', content={'title': '方案', 'summary': '初稿完成', 'status': 'in_progress', 'blocker': '', 'nextStep': '等待确认'})
        db.add(work); await db.flush()
        revision = WorkRevision(company_id=actor.company_id, owner_id=actor.id, work_id=work.id, revision=1, content=work.content, source_ids=[], created_at=instant)
        db.add(revision); await db.flush()
        report, job = await ensure_report(db, actor, 'weekly', instant.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Shanghai')).date())
    return report, job, work
