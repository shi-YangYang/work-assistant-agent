"""Server-only authenticated credentials. Never create/replace a key while reading."""
import base64
import os
from pathlib import Path
import stat
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SecretUnavailable(ValueError):
    def __init__(self):
        super().__init__('模型密钥保护不可用，请让部署管理员检查密钥文件；已有配置未改变')


def read_key(path: Path) -> bytes:
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError()
        if os.name != 'nt' and stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ValueError()
        value = path.read_bytes()
        if len(value) != 32:
            raise ValueError()
        return value
    except (OSError, ValueError):
        raise SecretUnavailable() from None


def initialize_key(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # O_EXCL prevents replacing a key that is already paired with database backups.
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        read_key(path)
        return
    with os.fdopen(fd, 'wb') as file:
        file.write(os.urandom(32))
        file.flush()
        os.fsync(file.fileno())


def encrypt(path, value, company, service, revision):
    nonce = os.urandom(12)
    aad = f'{company}:{service}:{revision}'.encode()
    return base64.b64encode(nonce + AESGCM(read_key(path)).encrypt(nonce, value.encode(), aad)).decode()


def decrypt(path, value, company, service, revision):
    try:
        raw = base64.b64decode(value, validate=True)
        return AESGCM(read_key(path)).decrypt(raw[:12], raw[12:], f'{company}:{service}:{revision}'.encode()).decode()
    except Exception:
        raise SecretUnavailable() from None
