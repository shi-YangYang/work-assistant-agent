"""One mutation boundary shared by REST and authenticated agent actions."""
from sqlalchemy import select
from app.core.attachment_limits import MAX_ATTACHMENTS, MAX_AUDIO_ATTACHMENTS
from app.core.errors import problem
from app.core.versions import version
from app.db.idempotency import idem_begin, idem_save
from app.modules.work.models import WorkItem, WorkMaterial, WorkRevision, WorkUpdate
from app.modules.work.content.document import WorkDocument, edit_document, material_ids, plain_text
from app.modules.work.materials.service import bind_materials, require_materials
from app.modules.work.updates.service import save_update, update_dto
from app.modules.work.service import save_work
from app.modules.work.serializers import work_content, work_dto
from app.security.ownership import owned
from app.security.access import require
from app.security.locks import company_lock


async def normalize_material_refs(db, work, body, bound):
    rows = (await db.scalars(select(WorkMaterial).where(WorkMaterial.id.in_(bound)))).all()
    mapping = {row.source['attachmentId']: row.id for row in rows if row.source.get('attachmentId')}
    def visit(node):
        if node.get('type') == 'material':
            identifier = node['attrs']['materialId']
            node['attrs']['materialId'] = mapping.get(identifier, identifier)
        for child in node.get('content', []):
            visit(child)
    for node in body['content']:
        visit(node)
    return body, mapping


async def mutate_record(db, actor, identifier, changes, *, expected=None, settings=None, origin='manual', kind='content', update_id=None, expected_update=None, conversation_id=None, sources=(), access=None, links=(), publication=None):
    await company_lock(db, actor.company_id)
    work = await owned(db, WorkItem, identifier, actor, lock=True) if identifier else None
    if work:
        await require(db, actor, work.access, retained=True)
        version(work, expected)
    previous = None
    if update_id:
        previous = await db.scalar(select(WorkUpdate).where(WorkUpdate.id == update_id, WorkUpdate.work_id == work.id, WorkUpdate.owner_id == actor.id).with_for_update())
        if not previous or previous.deleted:
            problem(404, '进展不存在或已删除')
        version(previous, expected_update)
    base = work_content(work.content, work.id) if work else {}
    previous_revision = work.revision if work else None
    scalar_fields = ('title', 'status', 'dueDate', 'blocker', 'nextStep')
    patch = {key: value for key, value in changes.items() if key in scalar_fields}
    if not work:
        work = await save_work(db, actor, patch, legacy_progress=False, origin='assistant' if origin == 'assistant_confirmed' else origin, revision_origin=origin, sources=sources, access=access, links=links, publication=publication)
    bound = await bind_materials(db, actor, work, changes.get('materials', []), settings, conversation_id=conversation_id)
    current_ids = list(base.get('materialIds', []))
    if 'body' in changes or 'bodyEdits' in changes:
        body = WorkDocument.model_validate(changes['body']).model_dump() if 'body' in changes else edit_document(base.get('body', {'schemaVersion': 1, 'content': []}), changes['bodyEdits'])
        from app.modules.work.content.checklist import assign_new_item_ids
        body = assign_new_item_ids(body, base.get('body', {}))
        body, mapping = await normalize_material_refs(db, work, body, bound)
        refs = material_ids(body)
        await require_materials(db, actor, work, refs)
        if body != WorkDocument.model_validate(base.get('body', {'schemaVersion': 1, 'content': []})).model_dump() or any(edit['action'] != 'set_checked' for edit in changes.get('bodyEdits', [])) or 'body' in changes:
            patch.update(body=body, bodyText=plain_text(body))
    else:
        refs, mapping = material_ids(base.get('body', {})), {}
    requested_ids = [mapping.get(value, value) for value in changes.get('materialIds', [])]
    _, selected_attachments = await require_materials(db, actor, work, list(dict.fromkeys([*requested_ids, *bound])))
    if len(selected_attachments) > MAX_ATTACHMENTS or sum(a.kind == 'audio' for a in selected_attachments) > MAX_AUDIO_ATTACHMENTS:
        problem(422, '单次最多添加 20 个附件，其中语音最多 3 段')
    all_ids = list(dict.fromkeys([*current_ids, *refs, *bound, *requested_ids]))
    patch['materialIds'] = all_ids
    update = None
    update_changed = False
    if kind.startswith('update_'):
        from app.modules.work.records.record_schemas import UpdateInput
        text = changes.get('text', previous.text if previous else '') if kind != 'update_delete' else previous.text
        existing_ids = previous.material_ids if previous and 'materialIds' not in changes else requested_ids
        ids = list(dict.fromkeys([*existing_ids, *bound])) if kind != 'update_delete' else previous.material_ids
        if kind != 'update_delete':
            text = text.strip()
            UpdateInput(text=text, materialIds=ids)
            _, attachments = await require_materials(db, actor, work, ids)
            if sum(a.kind == 'audio' for a in attachments) > 3:
                problem(422, '每条进展最多添加 3 段语音')
        update_changed = not previous or kind == 'update_delete' or text != previous.text.strip() or ids != previous.material_ids
        # summary follows the newest entry, including when editing an older one.
        # An unchanged edit must not temporarily replace that projection.
        if update_changed:
            latest = await db.scalar(select(WorkUpdate).where(WorkUpdate.work_id == work.id, WorkUpdate.deleted.is_(False)).order_by(WorkUpdate.created_at.desc(), WorkUpdate.id.desc()).limit(1))
            if not previous or latest and latest.id == previous.id:
                patch['summary'] = text[:4000]
    if identifier:
        work = await save_work(db, actor, patch, identifier=work.id, expected=expected, sources=sources, origin=origin, access=access, links=links, publication=publication, legacy_progress=False, force_revision=update_changed)
    else:
        # Initial creation and its material bindings form one work version.
        work.content = {**work.content, **patch}
        revision = await db.scalar(select(WorkRevision).where(WorkRevision.work_id == work.id, WorkRevision.revision == work.revision))
        revision.content = dict(work.content)
        revision.access, revision.business_links = work.access, work.business_links
    if kind.startswith('update_') and (update_changed or previous_revision != work.revision):
        update = await save_update(db, actor, work, text, ids, origin, identifier=update_id, expected=expected_update, deleted=kind == 'update_delete')
        await db.flush()
        latest = await db.scalar(select(WorkUpdate).where(WorkUpdate.work_id == work.id, WorkUpdate.deleted.is_(False)).order_by(WorkUpdate.created_at.desc(), WorkUpdate.id.desc()).limit(1))
        work.content = {**work.content, 'summary': latest.text[:4000] if latest else ''}
    elif previous:
        update = previous
    revision = await db.scalar(select(WorkRevision).where(WorkRevision.work_id == work.id, WorkRevision.revision == work.revision))
    metadata = {'_changeKind': 'properties' if kind == 'content' and identifier and not ({'body', 'bodyEdits', 'materials', 'materialIds'} & changes.keys()) else kind}
    if update:
        metadata.update(_updateId=update.id, _updateRevision=update.revision, _updateDeleted=update.deleted, _updateText=update.text, _updateMaterialIds=update.material_ids)
    if previous_revision != work.revision:
        revision.content = {**work.content, **metadata}
    await db.flush()
    return {'work': work_dto(work), 'materialIds': bound, 'unchanged': previous_revision == work.revision, **({'update': update_dto(update)} if update else {})}


async def record_command(db, actor, identifier, body, key, settings, *, kind='content', update_id=None):
    payload = body.model_dump(mode='json', exclude_unset=True)
    action = f'work-record:{identifier or "new"}:{kind}:{update_id or ""}'
    prior, digest = await idem_begin(db, actor, action, key, payload)
    if prior:
        work = await owned(db, WorkItem, prior['work']['id'], actor)
        await require(db, actor, work.access, retained=True)
        return prior
    expected = payload.pop('expectedRevision', None)
    expected_update = payload.pop('expectedUpdateRevision', None)
    try:
        result = await mutate_record(db, actor, identifier, payload, expected=expected, settings=settings, kind=kind, update_id=update_id, expected_update=expected_update)
    except ValueError as error:
        problem(422, str(error))
    return idem_save(db, actor, action, key, digest, result)


async def remove_material_command(db, actor, identifier, material_id, body, key, *, origin='manual'):
    action = f'work-material-remove:{identifier}:{material_id}'
    prior, digest = await idem_begin(db, actor, action, key, body.model_dump())
    work = await owned(db, WorkItem, identifier, actor, lock=True)
    await require(db, actor, work.access, retained=True)
    if prior:
        return prior
    version(work, body.expectedRevision)
    row = await db.scalar(select(WorkMaterial).where(WorkMaterial.id == material_id, WorkMaterial.work_id == work.id))
    if not row or row.removed:
        problem(404, '材料不存在或已移除')
    version(row, body.expectedMaterialRevision)
    if material_id in material_ids(work.content.get('body', {})) or await db.scalar(select(WorkUpdate.id).where(WorkUpdate.work_id == work.id, WorkUpdate.deleted.is_(False), WorkUpdate.material_ids.contains([material_id])).limit(1)):
        problem(409, '材料仍被正文或进展引用，请先移除对应引用')
    row.removed, row.revision = True, row.revision + 1
    work = await save_work(db, actor, {'materialIds': [i for i in work.content.get('materialIds', []) if i != material_id]}, identifier=work.id, expected=work.revision, legacy_progress=False, origin='assistant' if origin == 'assistant_confirmed' else origin, revision_origin=origin)
    revision = await db.scalar(select(WorkRevision).where(WorkRevision.work_id == work.id, WorkRevision.revision == work.revision))
    revision.content = {**work.content, '_changeKind': 'material_remove'}
    return idem_save(db, actor, action, key, digest, {'work': work_dto(work), 'materialIds': []})
