"""User-initiated, pinned model downloads, atomically published after validation."""
from __future__ import annotations

import hashlib
import json
import shutil
import ssl
import certifi
import threading
import urllib.parse
import urllib.request
from pathlib import Path

from .repository import DomainError

MODEL_ID = 'Systran/faster-whisper-small'
REVISION = '536b0662742c02347bc0e980a01041f333bce120'
FILES = {
    'config.json': (2370, 'b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828'),
    'model.bin': (483546902, '3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671'),
    'tokenizer.json': (2203239, 'fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab'),
    'vocabulary.txt': (459861, '34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913'),
    'README.md': (1998, '329373481008c7c38654aff8ecdcf0163c211557cc7ba8e2ef6f2f84b4f75ec8'),
}
DOWNLOAD_BYTES = sum(item[0] for item in FILES.values())
REQUIRED_BYTES = DOWNLOAD_BYTES * 2 + 50_000_000


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme != 'https' or not (parsed.hostname == 'huggingface.co' or (parsed.hostname or '').endswith('.huggingface.co') or (parsed.hostname or '').endswith('.hf.co')):
            raise OSError('Unexpected model redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def verify_files(path, cancelled=lambda: False):
    for name, (size, checksum) in FILES.items():
        file = path / name
        if path.is_symlink() or file.is_symlink() or file.stat().st_size != size:
            raise OSError('Model file size mismatch')
        digest = hashlib.sha256()
        with file.open('rb') as source:
            while data := source.read(1024 * 1024):
                if cancelled():
                    raise InterruptedError('Cancelled')
                digest.update(data)
        if digest.hexdigest() != checksum:
            raise OSError('Model checksum mismatch')


class ModelManager:
    def __init__(self, root, worker):
        self.root = root / 'models'
        self.path = self.root / ('whisper-small-' + REVISION)
        self.staging = self.root / ('whisper-small-' + REVISION + '.staging')
        self.worker = worker
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.thread = None
        self.response = None
        self.state = 'missing'
        self.downloaded = 0
        self.error = None
        if self.path.exists():
            self._begin(False)

    def status(self):
        with self.lock:
            return {'modelId': MODEL_ID, 'revision': REVISION, 'state': self.state,
                    'downloadedBytes': self.downloaded, 'totalBytes': DOWNLOAD_BYTES,
                    'requiredBytes': REQUIRED_BYTES, 'source': 'Hugging Face · SYSTRAN',
                    'license': 'MIT', 'error': self.error}

    def _begin(self, download):
        self.cancelled.clear()
        self.state = 'downloading' if download else 'verifying'
        self.downloaded = 0
        self.error = None
        self.thread = threading.Thread(target=self._prepare, args=(download,), name='model-prepare', daemon=True)
        self.thread.start()

    def download(self):
        with self.lock:
            if self.state in ('downloading', 'verifying', 'ready') or (self.thread and self.thread.is_alive()):
                return self.status()
            self._begin(True)
            return self.status()

    def cancel(self):
        self.cancelled.set()
        if self.state == 'verifying' and hasattr(self.worker, 'interrupt'):
            self.worker.interrupt()
        # Reads have a finite network timeout. Do not block the control loop on a stalled socket.
        return self.status()

    def _prepare(self, download):
        target = self.staging if download else self.path
        try:
            if self.root.is_symlink() or target.is_symlink():
                raise OSError('Invalid model directory')
            self.root.mkdir(parents=True, exist_ok=True)
            if download:
                if shutil.disk_usage(self.root).free < REQUIRED_BYTES:
                    raise DomainError('model_space', '磁盘空间不足，请至少预留 1.1 GB 后重试下载。')
                if self.staging.exists():
                    shutil.rmtree(self.staging)
                self.staging.mkdir()
                # urllib honors the OS proxy settings on macOS/Windows and normal TLS validation.
                opener = urllib.request.build_opener(HTTPSRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())))
                for name, (size, _checksum) in FILES.items():
                    if self.cancelled.is_set():
                        raise InterruptedError('Cancelled')
                    url = f'https://huggingface.co/{MODEL_ID}/resolve/{REVISION}/{name}'
                    with opener.open(url, timeout=10) as response, (target / name).open('xb') as destination:
                        count = 0
                        while data := response.read(256 * 1024):
                            if self.cancelled.is_set():
                                raise InterruptedError('Cancelled')
                            count += len(data)
                            if count > size:
                                raise OSError('Unexpected model size')
                            destination.write(data)
                            with self.lock:
                                self.downloaded += len(data)
                        if count != size:
                            raise OSError('Incomplete model download')
            with self.lock:
                self.state = 'verifying'
            verify_files(target, self.cancelled.is_set)
            if self.cancelled.is_set():
                raise InterruptedError('Cancelled')
            self.worker.load(target)
            if self.cancelled.is_set():
                raise InterruptedError('Cancelled')
            if download:
                if self.path.exists():
                    # Only the fixed, previously invalid model directory can be replaced.
                    shutil.rmtree(self.path)
                target.replace(self.path)
            with self.lock:
                self.state = 'ready'
                self.downloaded = DOWNLOAD_BYTES
        except InterruptedError:
            with self.lock:
                self.state, self.error = 'missing', None
        except Exception as exc:
            with self.lock:
                self.state = 'missing' if self.cancelled.is_set() else 'error'
                self.error = None if self.cancelled.is_set() else str(exc) if isinstance(exc, DomainError) else '模型准备失败，请检查网络、磁盘空间后重试下载；录音仍可使用。'
        finally:
            if download and self.staging.exists() and not self.staging.is_symlink():
                shutil.rmtree(self.staging, ignore_errors=True)

    def shutdown(self):
        self.cancel()
        if self.thread:
            self.thread.join(timeout=0.2)
