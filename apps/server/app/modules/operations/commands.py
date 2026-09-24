from app.core.errors import problem
from app.modules.operations.models import BusinessAction
from app.modules.operations.service import confirm as actions_confirm
from app.modules.reports.models import Report
from app.modules.work.models import WorkItem
from app.security.ownership import owned


async def confirm_business_action_command(identifier, choice, body, actor, db, settings):
    if choice not in ('confirm', 'cancel'):
        problem(404, '操作不存在')
    row = await owned(db, BusinessAction, identifier, actor)
    target_id = row.result.get('objectId') or row.params.get('targetId')
    target = await db.get(Report if row.action.endswith('report') else WorkItem, target_id) if target_id else None
    cleanup_owner = target.owner_id if target and target.company_id == actor.company_id else actor.id
    result = await actions_confirm(db, actor, identifier, body.expectedRevision, cancel=choice == 'cancel')
    await db.commit()
    from app.modules.operations.deletion import clean_files
    try:
        await clean_files(db, settings, cleanup_owner)
    except OSError:
        pass  # Persistent attachment tombstones are retried by normal cleanup.
    return result
