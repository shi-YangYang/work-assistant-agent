"""Deliver a verified destination gap without asking the model to rewrite it."""
from sqlalchemy import select

from app.agent.actions.interactions import ask
from app.modules.interactions.schemas import MAX_QUESTIONS, MAX_QUESTION_OPTIONS
from app.modules.work.models import WorkItem
from app.security.access import valid
from app.tasks.feedback.material_requirements import collections
from app.tasks.lease import lease


async def ask_destination(context, *, recovery=None):
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        gaps = {entry.get('recovery', {}).get('materialSelectionId')
                for entry in job.result.get('toolOutcomes', [])
                if entry.get('category') == 'missing_info'
                and entry.get('recovery', {}).get('owner') == 'user'
                and {item.get('field') for item in entry.get('recovery', {}).get('missingInputs', [])} == {'target'}}
        if recovery:
            gaps.add(recovery.get('materialSelectionId'))
        selected = [item for item in collections(job)
                    if item['id'] in gaps and item['destination'] == 'unselected' and item['sources']]
        if not selected:
            return None
        # Search results are candidates, never a choice. Only offer records
        # already read at this exact revision and still owned by this user.
        reads = context.read_versions
        works = (await db.scalars(select(WorkItem).where(WorkItem.id.in_(reads),
            WorkItem.owner_id == actor.id, WorkItem.company_id == actor.company_id,
            WorkItem.deleted.is_(False)).order_by(WorkItem.id))).all()
        options = [{'id': 'work-' + work.id, 'label': work.title[:120],
                    'objectType': 'work', 'objectId': work.id}
                   for work in works if reads[work.id] == work.revision
                   and await valid(db, actor, work.access, retained=True)][:MAX_QUESTION_OPTIONS - 1]
        options.append({'id': 'new', 'label': '新建一条工作'})
        questions = [{'id': 'material-destination-' + item['id'][:32],
            'prompt': (f'这 {len(item["sources"])} 份文件要保存到哪里？' if len(selected) == 1
                       else f'“{item["quote"][:80]}”中的 {len(item["sources"])} 份文件要保存到哪里？'),
            'type': 'single', 'options': options, 'allowCustom': True} for item in selected[:MAX_QUESTIONS]]
    return await ask(context, questions, append_pending=True)
