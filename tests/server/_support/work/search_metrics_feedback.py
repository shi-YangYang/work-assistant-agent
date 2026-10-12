"""Shared controlled fixtures extracted from test_search_metrics_feedback."""
from app.modules.work.models import WorkItem, WorkRevision


def content(title='工作', status='in_progress', blocker=''):
    return {'title':title,'summary':'方案摘要','status':status,'blocker':blocker,'nextStep':'下一步'}


async def work(db, actor, value, stamp, *, revision=1, access=None):
    item = WorkItem(company_id=actor.company_id,owner_id=actor.id,title=value['title'],content=value,updated_at=stamp,revision=revision,access=access or {})
    db.add(item); await db.flush()
    db.add(WorkRevision(company_id=actor.company_id,owner_id=actor.id,work_id=item.id,revision=revision,content=value,source_ids=[],created_at=stamp,access=access or {}))
    return item
