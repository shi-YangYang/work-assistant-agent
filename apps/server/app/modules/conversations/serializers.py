def conversation_dto(item, actor):
    return {'executionMode': actor.execution_mode, 'modeRevision': actor.mode_revision, 'fullAccessConfirmed': actor.full_access_confirmed, 'id': item.id, 'title': item.title, 'personaId': item.persona_id, 'revision': item.revision, 'updatedAt': item.updated_at.isoformat()}
