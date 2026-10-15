"""Message-local naming and byte identity; never merge attachment ownership or IDs."""
from pathlib import Path


def unique_names(names):
    reserved, used, result = set(names), set(), []
    for original in names:
        name = original
        suffix = Path(name).suffix[:16]
        stem = name[:-len(suffix)] if suffix else name
        number = 2
        while name in used:
            ending = f' ({number}){suffix}'
            name = stem[:180 - len(ending)] + ending
            number += 1
            if name in reserved:
                name = original
        used.add(name)
        reserved.add(name)
        result.append(name)
    return result


def content_key(item):
    checksum = getattr(item, 'sha256', '')
    if not checksum or not getattr(item, 'message_id', None):
        return (item.id,)
    # Equal bytes with different document formats need not parse the same way.
    return (item.company_id, item.owner_id, item.message_id, item.kind, checksum,
            item.size, Path(item.name).suffix.lower() if item.kind == 'document' else '')


def content_groups(attachments):
    groups = {}
    for item in attachments:
        groups.setdefault(content_key(item), []).append(item)
    return list(groups.values())
