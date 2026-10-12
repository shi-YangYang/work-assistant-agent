"""Shared controlled fixtures extracted from test_business_assistant."""
from app.modules.messages.models import Message
from app.modules.work.models import WorkItem, WorkRevision


def progress(title='采购报价', status='blocked', summary='报价待确认'):
    return {'title': title, 'summary': summary, 'status': status, 'blocker': '等供应商报价' if status == 'blocked' else '', 'nextStep': '核对报价'}


async def facts(sessions, actor, *, title='采购报价', status='blocked'):
    async with sessions.begin() as db:
        message = Message(company_id=actor.company_id, owner_id=actor.id, text='已确认关联原始材料', reply='PRIVATE-ASSISTANT-REPLY', private_context=False)
        work = WorkItem(company_id=actor.company_id, owner_id=actor.id, title=title, content=progress(title, status))
        db.add_all([message, work]); await db.flush()
        revision = WorkRevision(company_id=actor.company_id, owner_id=actor.id, work_id=work.id, revision=1, content=work.content, source_ids=[message.id])
        db.add(revision); await db.flush()
        return work, revision, message
