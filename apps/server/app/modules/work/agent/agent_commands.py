"""Adapt typed business actions to the shared work transaction."""
from app.core.errors import problem
from app.modules.work.records.record_commands import mutate_record, remove_material_command
from app.modules.work.records.record_schemas import AgentWorkChanges, MaterialRemove
from app.modules.work.models import WorkItem
from app.security.ownership import owned


RECORD_FIELDS = {'body', 'bodyEdits', 'materials', 'materialIds', 'update', 'removeMaterial'}


async def apply_action(db, actor, row, settings, *, confirmed=False, job=None):
    p = row.params
    changes = AgentWorkChanges.model_validate(p['changes']).model_dump(mode='json', exclude_unset=True)
    identifier = p['targetId'] if row.action == 'update_work' else None
    from app.modules.team.sources import canonical_token
    from app.security.access import resolve
    links = []
    if p.get('sourceTokens') and actor.role != 'admin':
        problem(403, '当前账号不能建立团队督办关联')
    for raw in p.get('sourceTokens', []):
        token = canonical_token(raw)
        evidence = (job.access if job else row.access).get('reads', {}).get(token)
        if not evidence or evidence.get('type') not in ('work', 'report'):
            problem(403, '督办来源必须来自实际读取的工作或报告')
        await resolve(db, actor, evidence, latest=True)
        links.append({'token': token, 'evidence': evidence})
    if 'removeMaterial' in changes:
        removal = changes['removeMaterial']
        result = await remove_material_command(db, actor, identifier, removal['id'], MaterialRemove(expectedRevision=p['expectedRevision'], expectedMaterialRevision=removal['expectedRevision']), 'action:' + row.id, origin='assistant_confirmed' if confirmed else 'assistant')
    else:
        update = changes.pop('update', None)
        kind = 'update_' + update['action'] if update else 'content'
        update_id = update.get('id') if update else None
        expected_update = update.get('expectedRevision') if update else None
        if update:
            changes.update({key: update[key] for key in ('text', 'materialIds', 'materials') if key in update})
        if p.get('sharedAttachmentIds'):
            changes['materials'] = [*changes.get('materials', []), *({'attachmentId': value} for value in p['sharedAttachmentIds'])]
        if 'summary' in changes and not identifier and not {'body', 'bodyEdits'} & changes.keys():
            from app.modules.work.content.document import from_text
            changes['body'] = from_text(changes.pop('summary'))
        elif 'summary' in changes and identifier:
            if {'body', 'bodyEdits'} & changes.keys():
                problem(422, '正文与进展请作为独立保存步骤')
            changes['text'] = changes.pop('summary')
            kind = 'update_create'
        from app.modules.operations.mutations.publication import snapshot
        publication = snapshot({}, message_ids=[row.message_id], attachments=p.get('sharedAttachmentIds', [])) if p.get('sharedAttachmentIds') else None
        result = await mutate_record(db, actor, identifier, changes, expected=p.get('expectedRevision'), settings=settings,
            origin='assistant_confirmed' if confirmed else 'assistant', kind=kind, update_id=update_id, expected_update=expected_update,
            conversation_id=row.conversation_id, sources=[row.message_id], access=row.access, links=links, publication=publication)
    work = result['work']
    from app.modules.deliverables.service import link_work
    await link_work(db, actor, p.get('deliverableReference'), row, await db.get(WorkItem, work['id']))
    # The receipt covers explicitly referenced existing materials too, but
    # never credits unrelated files merely retained by the work transaction.
    material_ids = list(dict.fromkeys([*result.get('materialIds', []),
        *(identifier for identifier in changes.get('materialIds', []) if identifier in work.get('materialIds', []))]))
    return {'objectType': 'work', 'objectId': work['id'], 'revision': work['revision'], 'changedFields': sorted(p['changes']),
            'updateId': result.get('update', {}).get('id'), 'updateRevision': result.get('update', {}).get('revision'), 'materialIds': material_ids}


async def action_preview(db, actor, work, changes):
    """Validate and describe pending mutations without binding files or writing."""
    changes = AgentWorkChanges.model_validate(changes).model_dump(mode='json', exclude_unset=True)
    if changes.get('update'):
        from app.modules.work.models import WorkUpdate
        from app.core.versions import version
        from sqlalchemy import select
        update = changes['update']
        if update['action'] != 'create':
            if not work:
                problem(422, '新建工作不能更正已有进展')
            entry = await db.scalar(select(WorkUpdate).where(WorkUpdate.id == update['id'], WorkUpdate.work_id == work.id, WorkUpdate.deleted.is_(False)))
            if not entry:
                problem(404, '进展不存在或已删除')
            version(entry, update['expectedRevision'])
            changes['update'] = {**update, 'before': entry.text}
    if 'bodyEdits' in changes:
        from app.modules.work.content.document import edit_previews
        from app.modules.work.serializers import work_content
        current = work_content(work.content, work.id).get('body', {'schemaVersion': 1, 'content': []}) if work else {'schemaVersion': 1, 'content': []}
        changes['bodyEdits'] = edit_previews(current, changes['bodyEdits'])
    names = {}
    from app.modules.attachments.documents import visible_attachment
    from app.modules.deliverables.queries import get_deliverable
    for source in [*changes.get('materials', []), *changes.get('update', {}).get('materials', [])]:
        if source.get('attachmentId'):
            attachment = await visible_attachment(db, source['attachmentId'], actor)
            if attachment.owner_id != actor.id:
                problem(403, '只能保存本人明确选中的材料')
            names[source['attachmentId']] = attachment.name
        else:
            _, record = await get_deliverable(db, actor, source['deliverableId'], source['revision'])
            file = next((f for f in record.files if f['id'] == source['fileId']), None)
            if not file:
                problem(404, '成果文件不存在')
            names[source['fileId']] = file['name']
    ids = [*changes.get('materialIds', []), *changes.get('update', {}).get('materialIds', [])]
    if changes.get('removeMaterial'):
        ids.append(changes['removeMaterial']['id'])
    if ids:
        if not work:
            problem(422, '新工作不能引用其他工作的材料')
        from app.modules.work.materials.service import require_materials
        rows, attachments = await require_materials(db, actor, work, ids)
        by_id = {a.id: a for a in attachments}
        names.update({row.id: by_id[row.attachment_id].name for row in rows})
    return changes, names
