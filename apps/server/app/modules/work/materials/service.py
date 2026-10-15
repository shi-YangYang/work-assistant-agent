"""Work-owned durable file snapshots, independent of source conversations."""
import hashlib
import shutil
from pathlib import Path
from sqlalchemy import select, event
from app.core.errors import problem
from app.db.base import uid
from app.modules.attachments.models import Attachment, DocumentChunk
from app.modules.attachments.documents import attachment_dto, visible_attachment
from app.modules.work.models import WorkItem, WorkMaterial
from app.security.access import require, inherit
from app.modules.work.materials.queries import work_for_material



def material_dto(row, attachment, *, work_revision=None):
    dto = attachment_dto(attachment)
    if work_revision is not None:
        for key in ('url', 'previewUrl'):
            if dto.get(key):
                dto[key] += '?workRevision=' + str(work_revision)
        dto['workRevision'] = work_revision
    return {'id': row.id, 'workId': row.work_id, 'revision': 1 if work_revision is not None else row.revision, 'attachment': dto, 'createdAt': row.created_at.isoformat(), 'removed': False if work_revision is not None else row.removed}


async def require_materials(db, actor, work, ids, *, allow_removed=False):
    rows = list((await db.scalars(select(WorkMaterial).where(WorkMaterial.id.in_(ids), WorkMaterial.work_id == work.id))).all())
    if len(rows) != len(set(ids)) or any(row.removed for row in rows) and not allow_removed:
        problem(404, '材料不存在、已移除或不属于该工作')
    attachments = list((await db.scalars(select(Attachment).where(Attachment.id.in_([r.attachment_id for r in rows]), Attachment.deleted.is_(False)))).all())
    if len(attachments) != len(rows):
        problem(404, '材料文件已不可用')
    return rows, attachments


async def bind_materials(db, actor, work, sources, settings, *, conversation_id=None):
    if not sources:
        return []
    from app.security.locks import company_lock
    await company_lock(db, actor.company_id)
    if settings is None:
        raise ValueError('工作材料保存缺少存储配置')
    if len(sources) > 9:
        problem(422, '单次最多添加 9 个附件')
    result, audio = [], 0
    for raw in sources:
        source = raw.model_dump(exclude_none=True) if hasattr(raw, 'model_dump') else raw
        prior = await db.scalar(select(WorkMaterial).where(WorkMaterial.work_id == work.id, WorkMaterial.source == source, WorkMaterial.removed.is_(False)))
        if prior:
            result.append(prior.id)
            original = await db.get(Attachment, prior.attachment_id)
            audio += int(original.kind == 'audio')
            if audio > 3:
                problem(422, '单次最多添加 3 段语音')
            continue
        if source.get('attachmentId'):
            original = await visible_attachment(db, source['attachmentId'], actor, lock=True)
            if original.owner_id != actor.id:
                problem(403, '只能保存本人明确选中的材料')
            if original.message_id:
                from app.modules.messages.service import active_message
                message = await active_message(db, original.message_id, actor)
                if conversation_id and message.conversation_id != conversation_id:
                    problem(403, '材料不属于当前会话')
                await require(db, actor, message.access)
                inherit(actor, work, message)
            elif prior_work := await work_for_material(db, actor, original.id):
                inherit(actor, work, prior_work)
            path = settings.media_dir / original.id
            name, mime, size, checksum = original.name, original.mime, original.size, original.sha256
            kind, duration = original.kind, original.duration
        else:
            from app.modules.deliverables.queries import get_deliverable
            from app.modules.executions.files import file_path
            from app.modules.executions.sources import check_sources
            item, record = await get_deliverable(db, actor, source['deliverableId'], source['revision'], conversation_id=conversation_id)
            file = next((f for f in record.files if f['id'] == source['fileId']), None)
            if not file:
                problem(404, '成果文件不存在')
            await check_sources(db, actor, file.get('sources', []))
            inherit(actor, work, item)
            path = file_path(settings, file['storageKey'])
            name, mime, size, checksum = file['name'], file['mimeType'], file['size'], file['sha256']
            kind, duration, original = 'image' if mime.startswith('image/') else 'document', None, None
        from app.core.attachment_limits import MAX_IMAGE_BYTES, MAX_FILE_BYTES
        from app.modules.attachments.documents import document_type
        if size > (MAX_IMAGE_BYTES if kind == 'image' else MAX_FILE_BYTES):
            problem(413, '图片不得超过 30MB，其他文件不得超过 20MB')
        if kind == 'document' and not document_type(name, mime):
            problem(415, '此文件格式暂不支持保存为工作材料')
        if kind == 'image' and original is None and (mime not in ('image/png', 'image/jpeg', 'image/webp') or Path(name).suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp')):
            problem(415, '此成果图片格式暂不支持保存')
        audio += int(kind == 'audio')
        if audio > 3:
            problem(422, '单次最多添加 3 段语音')
        if not path.is_file() or path.is_symlink():
            problem(404, '源文件已不可用')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != checksum:
                problem(409, '源文件校验失败')
        identifier = uid()
        target = settings.media_dir / identifier
        register_copy_rollback(db, target)
        shutil.copyfile(path, target)
        target.chmod(0o600)
        clone = Attachment(id=identifier, company_id=actor.company_id, owner_id=actor.id, kind=kind, mime=mime, name=name, size=size, sha256=checksum, duration=duration,
            extraction_status=original.extraction_status if original else 'pending' if kind == 'document' else 'none',
            extraction_revision=original.extraction_revision if original else 0,
            extraction_info=dict(original.extraction_info or {}) if original else {}, parser_version=original.parser_version if original else '')
        db.add(clone)
        await db.flush()
        if original:
            chunks = (await db.scalars(select(DocumentChunk).where(DocumentChunk.attachment_id == original.id, DocumentChunk.revision == original.extraction_revision))).all()
            for chunk in chunks:
                db.add(DocumentChunk(company_id=actor.company_id, owner_id=actor.id, attachment_id=clone.id, revision=chunk.revision, ordinal=chunk.ordinal, location=chunk.location, text=chunk.text))
        material = WorkMaterial(company_id=actor.company_id, owner_id=actor.id, work_id=work.id, attachment_id=clone.id, source=source)
        db.add(material)
        await db.flush()
        if kind == 'document' and clone.extraction_status not in ('ready', 'partial'):
            from app.tasks.models import Job
            clone.extraction_status = 'pending'
            db.add(Job(company_id=actor.company_id, owner_id=actor.id, kind='document', target_id=clone.id))
        result.append(material.id)
    return result


async def material_page(db, actor, work, start=0, limit=20, *, historical_ids=None, work_revision=None):
    statement = select(WorkMaterial, Attachment).join(Attachment, Attachment.id == WorkMaterial.attachment_id).where(WorkMaterial.work_id == work.id, Attachment.deleted.is_(False))
    statement = statement.where(WorkMaterial.id.in_(historical_ids)) if historical_ids is not None else statement.where(WorkMaterial.removed.is_(False))
    rows = (await db.execute(statement.order_by(WorkMaterial.created_at, WorkMaterial.id).offset(start).limit(limit + 1))).all()
    return {'items': [material_dto(row, attachment, work_revision=work_revision) for row, attachment in rows[:limit]], 'nextCursor': start + limit if len(rows) > limit else None}


def register_copy_rollback(db, path):
    sync = db.sync_session
    if 'work_file_copies' not in sync.info:
        sync.info['work_file_copies'] = []
        def rollback(session, transaction):
            retained = []
            for created, owner in session.info.get('work_file_copies', []):
                current = owner
                while current is not None and current is not transaction:
                    current = current.parent
                if current is transaction:
                    created.unlink(missing_ok=True)
                else:
                    retained.append((created, owner))
            session.info['work_file_copies'] = retained
        def commit(session):
            if not session.in_nested_transaction():
                session.info['work_file_copies'] = []
        event.listen(sync, 'after_soft_rollback', rollback)
        event.listen(sync, 'after_commit', commit)
    sync.info['work_file_copies'].append((path, sync.get_nested_transaction() or sync.get_transaction()))
