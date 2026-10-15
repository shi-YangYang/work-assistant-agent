def attachment_inventory(attachments, transcript, transcript_revision):
    """Describe uploaded sources separately from their model-readable representations."""
    from app.modules.attachments.duplicates import content_key
    result, seen = [], {}
    for attachment in attachments:
        item = {'id': attachment.id, 'name': attachment.name, 'kind': attachment.kind, 'uploadStatus': 'received'}
        key = content_key(attachment)
        if key in seen:
            item['sameContentAs'] = seen[key]
        else:
            seen[key] = attachment.id
        if attachment.kind == 'audio':
            item['transcription'] = {'status': 'available' if transcript.strip() else 'unavailable', 'revision': transcript_revision}
        result.append(item)
    return result
