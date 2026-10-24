"""Resolve authenticated work receipts to immutable update/file evidence."""
from sqlalchemy import select
from app.modules.attachments.models import Attachment
from app.modules.work.models import WorkMaterial, WorkUpdate, WorkUpdateRevision


WORK_RECEIPT_POLICY = '''workRecordEvidence 是服务端按成功回执和不可变保存快照查询的工作记录证据。正文、进展条目和材料是独立原子操作：progressUpdate 证明指定进展内容已保存，正文 bodyText 不变是正常行为，summary 只是最近进展的兼容投影。不要因正文未变或 changedFields=update 而否认独立进展。
materials 每项明确给出工作材料 materialId、持久副本 savedAttachmentId、来源 source 及文件名 name；source.attachmentId 是用户选中的原附件，保存为工作材料时会复制文件，这三个 ID 不同是正常且必要的关联。按该映射核对答复中指名的附件，不能要求三个 ID 相等，也不能用其它材料或失败回执代替。保存成功不证明已读取或理解文件内容。revision/workRevision 是内部快照标识；unchanged 表示未产生修改，复用原记录；satisfiedFields 是已核对达到请求值的字段，不代表新修改。operation 表示实际保存的原子范围，不代表整项工作完成；继续任务可引用其中此前成功的步骤，但不能说重复执行了它。
'''


async def work_record_evidence(db, actor, cards):
    evidence = []
    for card in cards:
        if card.get('state') != 'succeeded' or card.get('objectType') != 'work':
            continue
        details = card.get('details', {})
        record = {'recordKind': 'saved_work_snapshot', 'receiptId': card['id'], 'workId': card['objectId'], 'workRevision': card['objectRevision'],
                  'unchanged': card.get('unchanged', False), 'satisfiedFields': card.get('satisfiedFields', []), 'changedFields': card.get('changedFields', []), 'changeKind': details.get('_changeKind', ''), 'materials': []}
        if card.get('updateId'):
            revision = await db.scalar(select(WorkUpdateRevision).join(WorkUpdate, WorkUpdate.id == WorkUpdateRevision.update_id).where(
                WorkUpdate.work_id == card['objectId'], WorkUpdate.company_id == actor.company_id, WorkUpdate.owner_id == actor.id,
                WorkUpdateRevision.update_id == card['updateId'], WorkUpdateRevision.revision == card['updateRevision'],
                WorkUpdateRevision.work_revision == (card.get('updateWorkRevision') or card['objectRevision'])))
            if revision:
                record['progressUpdate'] = {'id': revision.update_id, 'revision': revision.revision, 'text': revision.text,
                                            'deleted': revision.deleted, 'materialIds': revision.material_ids}
        identifiers = set(card.get('materialIds', [])) & set(details.get('materialIds', []))
        if identifiers:
            materials = (await db.execute(select(WorkMaterial, Attachment).join(Attachment, Attachment.id == WorkMaterial.attachment_id).where(
                WorkMaterial.id.in_(identifiers), WorkMaterial.work_id == card['objectId'],
                WorkMaterial.company_id == actor.company_id, WorkMaterial.owner_id == actor.id,
                Attachment.company_id == actor.company_id, Attachment.deleted.is_(False)).order_by(WorkMaterial.id))).all()
            record['materials'] = [{'materialId': material.id, 'savedAttachmentId': attachment.id, 'source': material.source,
                                    'name': attachment.name, 'sha256': attachment.sha256} for material, attachment in materials]
        evidence.append(record)
    return evidence
