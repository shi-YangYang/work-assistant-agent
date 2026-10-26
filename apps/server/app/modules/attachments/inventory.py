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


def inventory_summary(items):
    """Count exactly the visible inventory, retaining duplicate upload identities."""
    counts = {}
    for item in items:
        counts[item['kind']] = counts.get(item['kind'], 0) + 1
    return {'total': len(items), 'countsByKind': counts,
            'scope': '本消息可见的未删除上传附件，按附件计数、同内容不去重；received只表示收到，不表示已读，也不统计金额或冲突'}
