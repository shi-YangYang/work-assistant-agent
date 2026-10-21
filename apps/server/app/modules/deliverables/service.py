from app.core.digests import digest
from fastapi import HTTPException
from app.core.errors import problem
from app.db.base import now, uid
from app.modules.deliverables.models import Deliverable, DeliverableRevision, DeliverableLink
from app.modules.deliverables.queries import get_deliverable, check_reference, remember_source
from app.modules.deliverables.schemas import DeliverableContent
from app.security.access import inherit
from app.security.locks import company_lock
from sqlalchemy import select


async def save(db, actor, message, job, content, *, identifier='', expected_revision=0, read_revision=None, step=1, files=None):
    content = DeliverableContent.model_validate(content)
    if not 1 <= step <= 8 or not message.conversation_id:
        problem(422, '成果步骤或会话无效')
    await company_lock(db, actor.company_id)
    fingerprint = digest({'content': content.model_dump(), 'id': identifier, 'revision': expected_revision, **({'files': files} if files is not None else {})})
    prior = await db.scalar(select(DeliverableRevision).where(DeliverableRevision.message_id == message.id, DeliverableRevision.step == step))
    if prior:
        if prior.digest != fingerprint:
            raise HTTPException(status_code=409, detail={
                'code': 'saved_deliverable_step', 'message': '该步骤已保存成果，本次新内容未写入；进一步修改需新的用户请求。',
                'recovery': {'owner': 'none', 'nextAction': 'stop'}})
        item, record = await get_deliverable(db, actor, prior.deliverable_id, prior.revision, conversation_id=message.conversation_id)
        remember_source(job, actor, item, record)
        return item, record
    if identifier:
        if read_revision != expected_revision:
            problem(409, '请先读取要修改的成果版本')
        item, old = await get_deliverable(db, actor, identifier, conversation_id=message.conversation_id, lock=True)
        if item.revision != expected_revision:
            problem(409, '成果已更新，请读取最新版本后修改')
        known = {entry['id'] for entry in old.items}
        if any(entry.id and entry.id not in known for entry in content.items):
            problem(409, '条目编号不属于当前版本；新增条目请留空编号')
        item.revision += 1
    else:
        if expected_revision or any(entry.id for entry in content.items):
            problem(422, '新成果与新条目请留空编号')
        item = Deliverable(company_id=actor.company_id, owner_id=actor.id, conversation_id=message.conversation_id, title=content.title)
        db.add(item)
        await db.flush()
    item.title, item.updated_at = content.title, now()
    inherit(actor, item, job, message)
    record = DeliverableRevision(company_id=actor.company_id, owner_id=actor.id, deliverable_id=item.id, revision=item.revision, message_id=message.id, step=step, title=content.title, body=content.body, files=files if files is not None else (old.files if identifier else []), items=[{**entry.model_dump(), 'id': entry.id or uid()} for entry in content.items], digest=fingerprint)
    db.add(record)
    await db.flush()
    remember_source(job, actor, item, record)
    return item, record


async def link_work(db, actor, reference, row, work):
    if not reference:
        return
    item, record = await check_reference(db, actor, reference, row.conversation_id)
    if len(reference['itemIds']) != 1:
        problem(422, '一个工作操作必须对应一个成果条目')
    for item_id in reference['itemIds']:
        # Each atomic create/update refers to one stable plan item. A new action
        # may intentionally create a copy; retries reuse the original action.
        db.add(DeliverableLink(company_id=actor.company_id, owner_id=actor.id, deliverable_id=item.id, item_id=item_id, work_id=work.id, source_revision=record.revision, action_id=row.id))
