"""Pinned multi-model downloads and persistent defaults; inference remains offline."""
from __future__ import annotations

import hashlib
import json
import shutil
import ssl
import certifi
import threading
import urllib.parse
import urllib.request

from .asr_worker import config_for_mode, InferenceToken
from .repository import DomainError
from .model_catalog import CATALOG, MLX_CATALOG
from .inference_device import hardware, apply_device

MODEL_ID = CATALOG['small']['modelId']
REVISION = CATALOG['small']['revision']
FILES = CATALOG['small']['files']
DOWNLOAD_BYTES = sum(item[0] for item in FILES.values())
REQUIRED_BYTES = DOWNLOAD_BYTES * 2 + 50_000_000


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme != 'https' or not (parsed.hostname == 'huggingface.co' or (parsed.hostname or '').endswith('.huggingface.co') or (parsed.hostname or '').endswith('.hf.co')):
            raise OSError('Unexpected model redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def verify_files(path, cancelled=lambda: False, files=None):
    for name, (size, checksum) in (FILES if files is None else files).items():
        file = path / name
        if path.is_symlink() or file.is_symlink() or file.stat().st_size != size:
            raise OSError('Model file size mismatch')
        digest = hashlib.sha256()
        with file.open('rb') as source:
            while data := source.read(1024 * 1024):
                if cancelled(): raise InterruptedError('Cancelled')
                digest.update(data)
        if digest.hexdigest() != checksum:
            raise OSError('Model checksum mismatch')


class ModelManager:
    def __init__(self, root, worker, devices=None):
        self.root = root / 'models'
        self.settings_path = root / 'transcription-settings.json'
        self.worker = worker
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.prepare_token = None
        self.thread = None
        self.preparing = None
        self.references = lambda _model, _revision: False
        self.hardware = hardware() if devices is None else devices
        self.device = 'gpu' if self.hardware['gpuAvailable'] else 'cpu'
        self.default_id, self.language = 'small', 'zh'
        try:
            settings = json.loads(self.settings_path.read_text())
            self.entry(settings['modelId'])
            config_for_mode(settings['language'])
            self.default_id, self.language = settings['modelId'], settings['language']
            if settings.get('device') == 'cpu': self.device = 'cpu'
        except (OSError, ValueError, KeyError, TypeError, DomainError):
            pass
        self.states_by_backend = {backend: {id: {'state': 'missing', 'downloadedBytes': 0, 'error': None} for id in CATALOG}
                                  for backend in ('ctranslate2', 'mlx')}
        self.states = self.states_by_backend['ctranslate2']
        self.path = self.path_for('small', 'ctranslate2') # Compatibility for old integration tools.
        self.staging = self.path.with_name(self.path.name + '.staging')
        existing = [(backend, id) for backend in self.states_by_backend for id in CATALOG if self.path_for(id, backend).exists()]
        if existing:
            for backend, id in existing: self.states_by_backend[backend][id]['state'] = 'verifying'
            self.thread = threading.Thread(target=self._scan, args=(existing,), name='model-cache-check', daemon=True)
            self.thread.start()

    @property
    def backend(self):
        return 'mlx' if self.device == 'gpu' and self.hardware['gpuBackend'] == 'mlx' else 'ctranslate2'

    def entry(self, id, backend=None):
        if not isinstance(id, str) or id not in CATALOG:
            raise DomainError('invalid_model', '请选择列表中的转写模型。')
        return (MLX_CATALOG if (backend or self.backend) == 'mlx' else CATALOG)[id]

    def path_for(self, id, backend=None):
        backend = backend or self.backend
        prefix = 'whisper-mlx-' if backend == 'mlx' else 'whisper-'
        return self.root / (prefix + id + '-' + self.entry(id, backend)['revision'])

    def staging_for(self, id):
        return self.path_for(id).with_name(self.path_for(id).name + '.staging')

    def files(self, id, backend=None):
        backend = backend or self.backend
        return FILES if id == 'small' and backend == 'ctranslate2' else self.entry(id, backend)['files']

    def _scan(self, ids):
        try:
            for backend, id in ids:
                try:
                    if self.root.is_symlink(): raise OSError('Invalid directory')
                    verify_files(self.path_for(id, backend), self.cancelled.is_set, self.files(id, backend))
                    result = {'state': 'ready', 'downloadedBytes': sum(v[0] for v in self.files(id, backend).values()), 'error': None}
                except Exception:
                    result = {'state': 'error', 'downloadedBytes': 0, 'error': '模型文件不完整，请重新下载。'}
                with self.lock: self.states_by_backend[backend][id] = result
        finally:
            with self.lock: self.thread = None

    def _status(self, id):
        entry = self.entry(id)
        total = sum(item[0] for item in self.files(id).values())
        path = self.path_for(id)
        occupied = sum(p.stat().st_size for p in path.iterdir() if p.is_file() and not p.is_symlink()) if path.is_dir() and not path.is_symlink() else 0
        reason = '请先选择其他默认模型。' if id == self.default_id else '模型正在准备。' if id == self.preparing else '尚未完成的转写任务需要此模型，请先完成任务或取消重新转写。' if self.references(entry['modelId'], entry['revision']) else None
        return {'id': id, 'name': 'Whisper ' + id, 'modelId': entry['modelId'], 'revision': entry['revision'],
                **self.states_by_backend[self.backend][id], 'totalBytes': total, 'requiredBytes': total * 2 + 50_000_000,
                'occupiedBytes': occupied, 'parameters': entry['parameters'], 'description': entry['description'],
                'source': entry['modelId'], 'license': entry.get('license', 'MIT'),
                'default': id == self.default_id, 'deleteBlockedReason': reason}

    def status(self, id=None):
        with self.lock:
            if id is not None: return self._status(id)
            return {**self._status(self.default_id), 'defaultModel': self.default_id, 'language': self.language,
                    'device': self.device, 'hardware': self.hardware, 'backend': self.backend,
                    'preparingModel': self.preparing, 'models': [self._status(key) for key in CATALOG]}

    def config(self, language):
        return apply_device(config_for_mode(language), self.device, self.hardware)

    def selected(self):
        with self.lock:
            entry = self.entry(self.default_id)
            return entry['modelId'], entry['revision'], self.config(self.language)

    def resolve(self, model_id, revision):
        with self.lock:
            for backend, catalog in (('ctranslate2', CATALOG), ('mlx', MLX_CATALOG)):
                for id, entry in catalog.items():
                    if entry['modelId'] == model_id and entry['revision'] == revision:
                        if self.states_by_backend[backend][id]['state'] != 'ready':
                            label = 'GPU' if backend == 'mlx' else 'CPU／NVIDIA GPU'
                            raise DomainError('model_not_ready', f'请先在 {label} 设置中下载 Whisper {id}，此任务继续使用原来的模型和设备。')
                        return self.path_for(id, backend)
        name = next(('Whisper ' + id for id, entry in CATALOG.items() if entry['modelId'] == model_id), model_id)
        raise DomainError('model_mismatch', f'任务所需的 {name} 固定版本 {revision} 不可用，请保留资料并联系维护者。')

    def configure(self, id, language):
        with self.lock:
            self.entry(id)
            config_for_mode(language)
            if self.states_by_backend[self.backend][id]['state'] != 'ready' and id != self.default_id:
                raise DomainError('model_not_ready', '请先下载并准备此模型。')
            target = self.settings_path.with_suffix('.staging')
            if target.is_symlink() or self.settings_path.is_symlink(): raise OSError('Invalid settings file')
            target.write_text(json.dumps({'modelId': id, 'language': language, 'device': self.device}), encoding='utf-8')
            target.replace(self.settings_path)
            self.default_id, self.language = id, language
            return self.status()

    def set_device(self, device):
        with self.lock:
            apply_device(config_for_mode(self.language), device, self.hardware)
            if self.thread is not None:
                raise DomainError('model_busy', '模型正在准备，请完成或取消后切换推理设备。')
            previous = self.device
            self.device = device
            try:
                return self.configure(self.default_id, self.language)
            except Exception:
                self.device = previous
                raise

    def download(self, id=None):
        with self.lock:
            id = id or self.default_id
            self.entry(id)
            if self.states_by_backend[self.backend][id]['state'] == 'ready': return self.status()
            if self.thread is not None:
                raise DomainError('model_busy', '正在准备其他模型，请完成或取消后重试。')
            self.preparing = id
            self.cancelled.clear()
            self.prepare_token = InferenceToken()
            self.states_by_backend[self.backend][id] = {'state': 'downloading', 'downloadedBytes': 0, 'error': None}
            self.thread = threading.Thread(target=self._prepare, args=(id,), name='model-prepare', daemon=True)
            self.thread.start()
            return self.status()

    def cancel(self, id=None):
        with self.lock:
            if id is not None: self.entry(id)
            if id is None or id == self.preparing:
                self.cancelled.set()
                if self.prepare_token: self.prepare_token.cancel()
            return self.status()

    def remove(self, id):
        with self.lock:
            state = self._status(id)
            if state['deleteBlockedReason']: raise DomainError('model_in_use', state['deleteBlockedReason'])
            path = self.path_for(id)
            if self.root.is_symlink() or path.is_symlink(): raise OSError('Invalid model directory')
            if hasattr(self.worker, 'release'): self.worker.release(path)
            try:
                if path.exists(): shutil.rmtree(path)
            except OSError as exc:
                self.states_by_backend[self.backend][id]['state'] = 'error'
                self.states_by_backend[self.backend][id]['error'] = '模型文件未完整删除，请重试删除或重新下载。'
                raise DomainError('model_remove_failed', '模型文件仍被占用，请稍后重试删除。') from exc
            self.states_by_backend[self.backend][id] = {'state': 'missing', 'downloadedBytes': 0, 'error': None}
            return self.status()

    def _prepare(self, id):
        entry, files = self.entry(id), self.files(id)
        target, path = self.staging_for(id), self.path_for(id)
        terminal_state, terminal_error = 'ready', None
        try:
            if self.root.is_symlink() or target.is_symlink() or path.is_symlink(): raise OSError('Invalid model directory')
            self.root.mkdir(parents=True, exist_ok=True)
            required = sum(v[0] for v in files.values()) * 2 + 50_000_000
            if shutil.disk_usage(self.root).free < required:
                raise DomainError('model_space', f'磁盘空间不足，请至少预留 {required / 1e9:.1f} GB 后重试。')
            if target.exists(): shutil.rmtree(target)
            target.mkdir()
            opener = urllib.request.build_opener(HTTPSRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())))
            for name, (size, _checksum) in files.items():
                if self.cancelled.is_set(): raise InterruptedError('Cancelled')
                url = f"https://huggingface.co/{entry['modelId']}/resolve/{entry['revision']}/{name}"
                with opener.open(url, timeout=10) as response, (target / name).open('xb') as destination:
                    count = 0
                    while data := response.read(256 * 1024):
                        if self.cancelled.is_set(): raise InterruptedError('Cancelled')
                        count += len(data)
                        if count > size: raise OSError('Unexpected model size')
                        destination.write(data)
                        with self.lock: self.states_by_backend[self.backend][id]['downloadedBytes'] += len(data)
                    if count != size: raise OSError('Incomplete model download')
            with self.lock: self.states_by_backend[self.backend][id]['state'] = 'verifying'
            verify_files(target, self.cancelled.is_set, files)
            if self.cancelled.is_set(): raise InterruptedError('Cancelled')
            if hasattr(self.worker, 'validate'):
                self.worker.validate(target, self.config('zh'), self.prepare_token)
            else: self.worker.load(target)
            if self.cancelled.is_set(): raise InterruptedError('Cancelled')
            if path.exists(): shutil.rmtree(path)
            target.replace(path)
        except Exception as exc:
            terminal_state = 'missing' if self.cancelled.is_set() else 'error'
            terminal_error = None if self.cancelled.is_set() else str(exc) if isinstance(exc, DomainError) else '模型准备失败，请检查网络、磁盘空间与可用内存后重试。'
        finally:
            try:
                if target.exists() and not target.is_symlink(): shutil.rmtree(target)
            except OSError:
                terminal_state, terminal_error = 'error', '模型临时文件清理失败，请检查磁盘权限后重试。'
            with self.lock:
                self.states_by_backend[self.backend][id]['state'], self.states_by_backend[self.backend][id]['error'] = terminal_state, terminal_error
                if terminal_state == 'ready': self.states_by_backend[self.backend][id]['downloadedBytes'] = sum(v[0] for v in files.values())
                self.thread = self.preparing = self.prepare_token = None

    def shutdown(self):
        self.cancel()
        thread = self.thread
        if thread: thread.join(timeout=0.2)
