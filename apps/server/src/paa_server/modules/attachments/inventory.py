def attachment_inventory(attachments, transcript, transcript_revision):
    """Describe uploaded sources separately from their model-readable representations."""
    result = []
    for attachment in attachments:
        item = {'id': attachment.id, 'name': attachment.name, 'kind': attachment.kind, 'uploadStatus': 'received'}
        if attachment.kind == 'audio':
            item['transcription'] = {'status': 'available' if transcript.strip() else 'unavailable', 'revision': transcript_revision}
        result.append(item)
    return result
