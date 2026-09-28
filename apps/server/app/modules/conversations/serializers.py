def conversation_dto(item):
    return {'executionMode': item.execution_mode, 'modeRevision': item.mode_revision, 'fullAccessConfirmed': item.full_access_confirmed, 'id': item.id, 'title': item.title, 'personaId': item.persona_id, 'revision': item.revision, 'updatedAt': item.updated_at.isoformat()}
