def work_dto(work):
    return {'id': work.id, 'ownerId': work.owner_id, 'dueDate': None, 'origin': work.origin, **work.content, 'revision': work.revision, 'updatedAt': work.updated_at.isoformat(), 'hasBusinessLinks': bool(work.business_links)}


def draft_dto(draft):
    return {'id': draft.id, 'messageId': draft.message_id, 'workId': draft.work_id, 'baseRevision': draft.base_revision, 'content': draft.content, 'status': draft.status, 'revision': draft.revision}


def revision_origin(revision):
    if revision.origin in ('manual', 'assistant', 'assistant_confirmed'):
        return revision.origin
    # An older worker can still write after the schema migration. Recover the
    # origin from retained evidence without exposing private message IDs.
    if revision.source_ids or (revision.publication or {}).get('originMessageIds'):
        return 'assistant'
    return 'unknown'


def revision_work(work, revision):
    return {**work_dto(work), 'dueDate': None, **revision.content, 'revision': revision.revision, 'updatedAt': revision.created_at.isoformat(), 'historical': True, 'hasBusinessLinks':bool(revision.business_links)}
