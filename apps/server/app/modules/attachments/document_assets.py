"""Persistent private attachment derivatives; paths never come from a model."""
import asyncio
import hashlib
from pathlib import Path
import shutil
from contextlib import asynccontextmanager

ASSET_VERSION = 'document-assets-v1'


def directory(settings, item):
    # IDs are server generated; use a hash as defense in depth for filesystem keys.
    identifier = item.id if hasattr(item, 'id') else item
    key = hashlib.sha256(identifier.encode()).hexdigest()
    return settings.media_dir / '.documents' / key


def generation(settings, item):
    key = hashlib.sha256((item.sha256 + ':' + item.parser_version + ':' + ASSET_VERSION).encode()).hexdigest()[:32]
    return directory(settings, item) / key


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
