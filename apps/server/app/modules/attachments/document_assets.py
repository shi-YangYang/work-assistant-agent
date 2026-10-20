"""Persistent private attachment derivatives; paths never come from a model."""
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
from contextlib import asynccontextmanager
from app.integrations.parsing.document_storage import directory, generation
from app.integrations.parsing.document_rendering import RENDER_VERSION
from app.integrations.parsing.office_conversion import parse_office


def remove(settings, identifier):
    path = directory(settings, identifier)
    if path.exists():
        shutil.rmtree(path)


@asynccontextmanager
async def file_lock(path):
    """Cross-worker lock; kernel releases it after crashes, never holds a DB lock."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = path.open('a+b')
    try:
        while True:
            try:
                if __import__('os').name == 'posix':
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    import msvcrt
                    handle.seek(0); handle.write(b'0'); handle.flush(); handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except BlockingIOError:
                await asyncio.sleep(.05)
            except OSError:
                if __import__('os').name != 'nt':
                    raise
                await asyncio.sleep(.05)
        yield
    finally:
        handle.close()


@asynccontextmanager
async def heavy_slot(settings):
    # One host/media-root slot across all worker processes, including conversion.
    async with file_lock(settings.media_dir / '.documents' / '.heavy.lock'):
        yield


async def prepared_source(context, item):
    from app.integrations.parsing.formats import OFFICE_TARGETS
    from app.integrations.parsing.office_conversion import parse_office
    suffix = Path(item.name).suffix.lower()
    original = context.settings.media_dir / item.id
    if not original.is_file() or original.is_symlink():
        raise ValueError('原文件已不可用')
    def checksum():
        with original.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()
    if await asyncio.to_thread(checksum) != item.sha256:
        raise ValueError('原文件校验失败')
    if suffix not in OFFICE_TARGETS:
        return original, suffix
    target = generation(context.settings, item) / ('source' + OFFICE_TARGETS[suffix])
    async with file_lock(target.with_suffix('.lock')):
        if not target.is_file():
            async with heavy_slot(context.settings):
                trim(context.settings)
                if await copy_equivalent(context, item, target.name):
                    return target, OFFICE_TARGETS[suffix]
                result = await parse_office(original, suffix, destination=target, mode='convert')
            if result['status'] != 'ready':
                raise ValueError(result['info'].get('error', '文件转换失败'))
    return target, OFFICE_TARGETS[suffix]


def trim(settings):
    """Clean abandoned temporary files and reserve space for a bounded write.

    Call only while holding heavy_slot. Ready derivatives follow the original's
    lifecycle without cumulative quotas; low disk space only blocks new writes.
    """
    import time
    root = settings.media_dir / '.documents'
    now = time.time()
    for path in root.glob('*/*/*.pending-*'):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            stat = path.stat()
            if now - stat.st_mtime > 60:
                path.unlink(missing_ok=True)
        except FileNotFoundError:
            continue  # An authorized source deletion may run concurrently.
    from app.integrations.parsing.document_parser import MAX_OFFICE_OUTPUT, MAX_OFFICE_WORKSPACE
    reserve = MAX_OFFICE_WORKSPACE + MAX_OFFICE_OUTPUT
    if shutil.disk_usage(settings.media_dir).free < reserve + 512 * 1024 * 1024:
        raise ValueError('文件处理空间不足，本次页面暂时无法读取')


async def copy_equivalent(context, item, name):
    """Reuse owned identical bytes, but make an independent disposable copy."""
    from sqlalchemy import select
    from app.modules.attachments.models import Attachment
    async with context.sessions() as db:
        candidates = (await db.scalars(select(Attachment).where(Attachment.id != item.id, Attachment.owner_id == item.owner_id,
            Attachment.company_id == item.company_id, Attachment.sha256 == item.sha256, Attachment.parser_version == item.parser_version,
            Attachment.kind == 'document', Attachment.deleted.is_(False)))).all()
    target = generation(context.settings, item) / name
    for other in candidates:
        source = generation(context.settings, other) / name
        if source.is_file() and not source.is_symlink():
            temporary = target.with_name(target.name + '.pending-copy')
            try:
                await asyncio.to_thread(shutil.copyfile, source, temporary)
                temporary.chmod(0o600); temporary.replace(target)
                return True
            except FileNotFoundError:
                continue
            finally:
                temporary.unlink(missing_ok=True)
    return False


async def render_pages(context, item, pages, *, resolution='normal', sheet=''):
    try:
        return await _render_pages(context, item, pages, resolution=resolution, sheet=sheet)
    finally:
        # Deletion can race native processing while no DB locks are held. Never
        # leave a newly recreated derivative directory behind a deleted original.
        if not (context.settings.media_dir / item.id).exists():
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
