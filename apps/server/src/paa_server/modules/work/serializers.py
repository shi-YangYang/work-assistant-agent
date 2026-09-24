def work_dto(work):
    return {'id': work.id, 'ownerId': work.owner_id, 'dueDate': None, 'origin': work.origin, **work.content, 'revision': work.revision, 'updatedAt': work.updated_at.isoformat(), 'hasBusinessLinks': bool(work.business_links)}


def draft_dto(draft):
    return {'id': draft.id, 'messageId': draft.message_id, 'workId': draft.work_id, 'baseRevision': draft.base_revision, 'content': draft.content, 'status': draft.status, 'revision': draft.revision}


def revision_work(work, revision):
    return {**work_dto(work), 'dueDate': None, **revision.content, 'revision': revision.revision, 'updatedAt': revision.created_at.isoformat(), 'historical': True, 'hasBusinessLinks':bool(revision.business_links)}
