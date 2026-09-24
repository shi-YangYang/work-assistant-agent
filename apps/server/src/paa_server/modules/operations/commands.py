from paa_server.core.errors import problem
from paa_server.modules.operations.models import BusinessAction
from paa_server.modules.operations.service import confirm as actions_confirm
from paa_server.modules.reports.models import Report
from paa_server.modules.work.models import WorkItem
from paa_server.security.ownership import owned


async def confirm_business_action_command(identifier, choice, body, actor, db, settings):
    if choice not in ('confirm', 'cancel'):
        problem(404, '操作不存在')
    row = await owned(db, BusinessAction, identifier, actor)
    target_id = row.result.get('objectId') or row.params.get('targetId')
    target = await db.get(Report if row.action.endswith('report') else WorkItem, target_id) if target_id else None
    cleanup_owner = target.owner_id if target and target.company_id == actor.company_id else actor.id
    result = await actions_confirm(db, actor, identifier, body.expectedRevision, cancel=choice == 'cancel')
    await db.commit()
    from paa_server.modules.operations.deletion import clean_files
    try:
        await clean_files(db, settings, cleanup_owner)
    except OSError:
        pass  # Persistent attachment tombstones are retried by normal cleanup.
    return result
