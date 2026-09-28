from app.agent.intent import authorize_intent
from app.core.digests import digest
from app.modules.work.models import WorkItem
from app.security.ownership import owned
from app.tasks.lease import lease
from sqlalchemy import select


async def authorize_suggestion(context, action, content, work_id=None, source_tokens=()):
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        target = await owned(db, WorkItem, work_id, actor) if work_id else None
        candidates = []
        if target:
            candidates = [{'id': row.id, 'title': row.title, 'summary': row.content.get('summary', '')} for row in (await db.scalars(select(WorkItem).where(WorkItem.company_id == actor.company_id, WorkItem.owner_id == actor.id, WorkItem.deleted.is_(False), WorkItem.title == target.title).limit(21))).all()]
        proposal = {'action': action, 'effect': 'prepare_suggestion', 'changes': content, 'targetId': work_id or '', 'target': target.title if target else '', 'targetCandidates': candidates, 'sourceTokens': list(source_tokens)}
    allowed, reason = await authorize_intent(context, proposal)
    if allowed:
        return None
    return {'state': 'not_requested' if digest(proposal) in context.unrequested_actions else 'clarification', 'message': reason or '本次未保存进展；请明确是否要记录到工作中'}
