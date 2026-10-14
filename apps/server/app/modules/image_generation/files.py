"""Check immutable image caches without holding a database connection."""
import hashlib
import os
import stat
from app.integrations.models.images.results import MAX_BYTES
from app.modules.executions.files import file_path


def identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def checked_files(settings, files):
    checked = []
    try:
        for item in files:
            size = item['size']
            if type(size) is not int or not 0 < size <= MAX_BYTES:
                return None
            path = file_path(settings, item['storageKey'])
            if not stat.S_ISREG(path.lstat().st_mode):
                return None
            flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
            with os.fdopen(os.open(path, flags), 'rb') as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size != size:
                    return None
                data = stream.read(size + 1)
                if len(data) != size or hashlib.sha256(data).hexdigest() != item['sha256'] or identity(before) != identity(os.fstat(stream.fileno())):
                    return None
            checked.append((path, identity(before)))
    except (OSError, KeyError, TypeError, ValueError):
        return None
    return checked or None


def unchanged(checked):
    """Fast check under the storage lock shared by publication and cleanup."""
    try:
        return bool(checked) and all(stat.S_ISREG((info := path.lstat()).st_mode) and identity(info) == expected for path, expected in checked)
    except OSError:
        return False
