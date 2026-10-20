"""Validate renderer versions and resolve private page references."""
import hashlib
from .document_storage import generation

RENDER_VERSION = 'poppler-page-v2'


def page_path(context, item, reference):
    import re
    renderer = reference.get('renderer', '')
    if not re.fullmatch(re.escape(RENDER_VERSION) + r'-[0-9a-f]{32}', renderer) or reference.get('revision') != item.extraction_revision or reference.get('sha256') != item.sha256:
        raise ValueError('页面来源已变化')
    page = reference.get('page')
    resolution = reference.get('resolution')
    if type(page) is not int or not 1 <= page <= 100000 or resolution not in ('normal', 'detail'):
        raise ValueError('页面来源无效')
    sheet = reference.get('sheet', '')
    key = hashlib.sha256(sheet.encode()).hexdigest()[:16] if sheet else 'document'
    return generation(context.settings, item) / f'{renderer}-{key}-{page}-{resolution}.png'
