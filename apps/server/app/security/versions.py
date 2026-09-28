"""Business revision validation, shared by runtime and snapshot readers."""


async def validate_cached_versions(db, actor, versions):
    from app.modules.work.models import WorkItem
    from app.modules.reports.models import Report
    from app.security.ownership import owned
    from app.security.access import require
    from app.integrations.models.transport import ProviderError
    for identifier, revision in versions.items():
        model = WorkItem if await db.get(WorkItem, identifier) else Report
        record = await owned(db, model, identifier, actor, read=True)
        if model == WorkItem:
            await require(db, actor, record.access, retained=True)
        if record.revision != revision:
            raise ProviderError('version_conflict', '已读取的工作或报告已变化，请重新提问以读取最新内容')


async def receipt_advanced_versions(db, actor, versions, message_id=None, *, task_id=None):
    """Accept only a contiguous series of this request's committed writes.

    A checkpoint summary may precede later tools in the same task. Its older
    read must not block recovery of those tools, but an external revision gap,
    deleted record or revoked permission still invalidates it.
    """
    from app.integrations.models.transport import ProviderError
    from app.modules.operations.models import BusinessAction
    from app.modules.reports.models import Report
    from app.modules.work.models import WorkItem
    from app.security.access import require
    from app.security.ownership import owned
    from sqlalchemy import select
    result = dict(versions)
    for identifier, revision in versions.items():
        model = WorkItem if await db.get(WorkItem, identifier) else Report
        record = await owned(db, model, identifier, actor, read=True)
        if model == WorkItem:
            await require(db, actor, record.access, retained=True)
        if record.revision == revision:
            continue
        receipts = (await db.scalars(select(BusinessAction).where(
            BusinessAction.owner_id == actor.id, BusinessAction.company_id == actor.company_id,
            (BusinessAction.task_id == task_id if task_id else BusinessAction.message_id == message_id), BusinessAction.state == 'succeeded',
            BusinessAction.action.in_(('update_work', 'edit_report', 'submit_report')),
            BusinessAction.result['objectId'].astext == identifier))).all()
        own_revisions = set()
        for receipt in receipts:
            if receipt.access.get('role', actor.role) != actor.role:
                continue
            await require(db, actor, receipt.access)
            own_revisions.add(receipt.result.get('revision'))
        if record.revision < revision or not set(range(revision + 1, record.revision + 1)).issubset(own_revisions):
            raise ProviderError('version_conflict', '已读取的工作或报告存在外部修改，请重新读取')
        result[identifier] = record.revision
    return result
