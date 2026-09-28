def conversation_dto(item):
    return {'id': item.id, 'title': item.title, 'personaId': item.persona_id, 'revision': item.revision, 'updatedAt': item.updated_at.isoformat()}
