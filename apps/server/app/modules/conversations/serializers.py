def conversation_dto(item):
    return {'id': item.id, 'title': item.title, 'revision': item.revision, 'updatedAt': item.updated_at.isoformat()}
