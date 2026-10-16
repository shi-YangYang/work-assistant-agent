"""Bounded native page rendering, private per-attachment cache, no model call."""
import asyncio
import hashlib
import json
from pathlib import Path
from app.modules.attachments.document_assets import file_lock, generation, heavy_slot, prepared_source, trim, copy_equivalent
from app.integrations.parsing.office_conversion import parse_office

RENDER_VERSION = 'poppler-page-v2'


async def render_pages(context, item, pages, *, resolution='normal', sheet=''):
    try:
        return await _render_pages(context, item, pages, resolution=resolution, sheet=sheet)
    finally:
        # Deletion can race native processing while no DB locks are held. Never
        # leave a newly recreated derivative directory behind a deleted original.
        if not (context.settings.media_dir / item.id).exists():
            from app.modules.attachments.document_assets import remove
            await asyncio.to_thread(remove, context.settings, item.id)


async def _render_pages(context, item, pages, *, resolution='normal', sheet=''):
    if resolution not in ('normal', 'detail') or not pages or len(pages) > 4 or any(type(page) is not int or page < 1 or page > 100000 for page in pages):
        raise ValueError('每次读取 1～4 页，分辨率为 normal 或 detail')
    original, suffix = await prepared_source(context, item)
    if suffix not in ('.pdf', '.docx', '.pptx', '.xlsx'):
        raise ValueError('此文件没有可渲染页面')
    if suffix == '.xlsx' and not sheet:
        raise ValueError('查看表格图片时请指定 sheet 工作表名称；数值统计应读取单元格原始数据')
    folder = generation(context.settings, item)
    from app.integrations.parsing.office_conversion import office_version
    renderer = RENDER_VERSION + '-' + (await office_version()).split(':')[-1]
    sheet_key = hashlib.sha256(sheet.encode()).hexdigest()[:16] if sheet else 'document'
    pdf = original if suffix == '.pdf' else folder / f'{renderer}-{sheet_key}.pdf'
    total = item.extraction_info.get('totalPages')
    metadata = folder / (pdf.name + '.json')
    if suffix != '.pdf':
        async with file_lock(folder / f'{sheet_key}.pdf.lock'):
            if not pdf.is_file():
                async with heavy_slot(context.settings):
                    trim(context.settings)
                    reused = await copy_equivalent(context, item, pdf.name)
                    if reused:
                        await copy_equivalent(context, item, metadata.name)
                    result = {'status': 'ready'} if reused else await parse_office(original, suffix, destination=pdf, mode='pdf', sheet=sheet)
                if result['status'] != 'ready':
                    raise ValueError(result['info'].get('error', '图片部分没读到'))
                if result.get('info', {}).get('totalPages'):
                    metadata.write_text(json.dumps({'totalPages': result['info']['totalPages']}))
        if metadata.is_file():
            total = json.loads(metadata.read_text()).get('totalPages')
    result = []
    for page in dict.fromkeys(pages):
        path = folder / f'{renderer}-{sheet_key}-{page}-{resolution}.png'
        async with file_lock(folder / 'pages.lock'):
            hit = path.is_file()
            if not hit:
                async with heavy_slot(context.settings):
                    trim(context.settings)
                    reused = await copy_equivalent(context, item, path.name)
                    packet = {'status': 'ready'} if reused else await parse_office(pdf, '.pdf', mode='page', destination=path, start=page, sheet=resolution, timeout=30)
                if packet['status'] != 'ready':
                    raise ValueError(packet['info'].get('error', '图片部分没读到'))
                total = packet.get('info', {}).get('totalPages', total)
        result.append({'attachmentId': item.id, 'revision': item.extraction_revision, 'sha256': item.sha256,
                       'page': page, 'totalPages': total, 'resolution': resolution, 'sheet': sheet, 'renderer': renderer,
                       'location': (f'工作表「{sheet}」 · ' if sheet else '') + (f'转换后第 {page} 页' if suffix == '.docx' else f'幻灯片 {page}' if suffix == '.pptx' else f'第 {page} 页'),
                       'cacheHit': hit})
    return result


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
