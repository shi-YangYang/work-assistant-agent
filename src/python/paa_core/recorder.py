"""One native capture session; the callback only copies into a bounded queue."""
from __future__ import annotations

import array
import math
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field

from .audio_store import AudioWriter, inspect_audio, inspect_recoverable_audio, recover_audio
from .repository import ACTIVE, DomainError, Repository, now, valid_id

ERROR_MESSAGES = {
    'device_unavailable': '无法打开默认麦克风，请检查系统麦克风权限与输入设备后重试。',
    'device_interrupted': '麦克风输入已中断，已尝试保留可恢复录音。请检查设备后开始新会议。',
    'audio_overflow': '音频输入或写入缓冲溢出，录音已中断，部分声音可能缺失。',
    'storage_write': '录音保存失败，请检查磁盘空间和目录权限；已写入的音频会保留。',
    'storage_commit': '会议元信息保存失败，请检查存储空间或数据库占用，保留数据后重新连接以恢复。',
    'system_suspend': '系统进入休眠，录音已中断并保留休眠前的内容。',
    'process_interrupted': '本地核心发生中断，已尝试保存可恢复的内容。',
}


class NativeInput:
    def __init__(self):
        import sounddevice
        self.sd = sounddevice

    def device(self):
        data = self.sd.query_devices(kind='input')
        sample_rate = int(data['default_samplerate'])
        self.sd.check_input_settings(device=data['index'], channels=1, dtype='int16', samplerate=sample_rate)
        return data['index'], data['name'], sample_rate

    def stream(self, device, sample_rate, block_size, callback):
        return self.sd.RawInputStream(device=device, samplerate=sample_rate, channels=1,
                                      dtype='int16', blocksize=block_size, callback=callback)


@dataclass
class Session:
    meeting_id: str
    state: str = 'starting'
    device_name: str | None = None
    sample_rate: int = 48000
    frames: int = 0
    input_level: float = 0
    error_code: str | None = None
    stop: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)
    chunks: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=64))
    next_sequence: int = 0
    next_offset: int = 0
    last_input: float = field(default_factory=time.monotonic)


class Recorder:
    def __init__(self, repository: Repository, source=None, writer_factory=AudioWriter, block_size=2048, queue_size=64):
        self.repository = repository
        self.source = source
        self.writer_factory = writer_factory
        self.block_size = block_size
        self.queue_size = queue_size
        self.lock = threading.RLock()
        self.session: Session | None = None
        self.dependency_error = None
        if self.source is None:
            try:
                self.source = NativeInput()
            except (ImportError, OSError):
                self.dependency_error = '录音组件不可用，请按 README 安装 Python 录音依赖后重新连接。'

    def status(self):
        with self.lock:
            current = self.session
            if current is None:
                return {'meetingId': None, 'state': 'idle', 'elapsedMs': 0, 'deviceName': None, 'inputLevel': 0, 'error': None}
            return {'meetingId': current.meeting_id, 'state': current.state,
                    'elapsedMs': round(current.frames * 1000 / current.sample_rate),
                    'deviceName': current.device_name, 'inputLevel': current.input_level if current.state == 'recording' else 0,
                    'error': {'code': current.error_code, 'message': ERROR_MESSAGES.get(current.error_code, '录音已中断，请检查存储与设备。')} if current.error_code else None}

    def start(self, operation_id: str):
        if not valid_id(operation_id):
            raise DomainError('invalid_params', '开始操作标识无效。')
        with self.lock:
            previous = self.repository.by_operation(operation_id)
            if previous:
                if self.session and self.session.meeting_id == previous['id']:
                    return self.status()
                return {'meetingId': previous['id'], 'state': previous['status'], 'elapsedMs': previous['durationMs'], 'deviceName': previous['deviceName'], 'inputLevel': 0, 'error': None}
            if self.session and self.session.state in ACTIVE:
                return self.status()
            if self.session and self.session.error_code == 'storage_commit':
                raise DomainError('storage_commit', ERROR_MESSAGES['storage_commit'])
            if self.dependency_error:
                raise DomainError('recording_unavailable', self.dependency_error)
            meeting_id = str(uuid.uuid4())
            self.repository.create(meeting_id, operation_id)
            current = Session(meeting_id, chunks=queue.Queue(maxsize=self.queue_size))
            self.session = current
            threading.Thread(target=self.run, args=(current,), name='meeting-recorder', daemon=True).start()
            return self.status()

    def stop(self, meeting_id: str, reason: str | None = None):
        if not valid_id(meeting_id):
            raise DomainError('invalid_params', '会议标识无效。')
        with self.lock:
            current = self.session
            if not current or current.meeting_id != meeting_id:
                previous = self.repository.get(meeting_id)
                return {'meetingId': meeting_id, 'state': previous['status'], 'elapsedMs': previous['durationMs'], 'deviceName': previous['deviceName'], 'inputLevel': 0, 'error': None}
            if current.state in ACTIVE:
                if reason:
                    current.error_code = current.error_code or reason
                current.state = 'stopping'
                current.stop.set()
            return self.status()

    def callback(self, current: Session, data, frames, _timing, status):
        if current.stop.is_set():
            return
        if status:
            current.error_code = 'audio_overflow'
            current.stop.set()
            return
        pcm = bytes(data)
        if len(pcm) != frames * 2 or frames > self.block_size:
            current.error_code = 'audio_overflow'
            current.stop.set()
            return
        try:
            current.chunks.put_nowait((current.next_sequence, current.next_offset, pcm))
        except queue.Full:
            current.error_code = 'audio_overflow'
            current.stop.set()
            return
        current.next_sequence += 1
        current.next_offset += frames
        current.last_input = time.monotonic()

    def run(self, current: Session):
        stream = None
        writer = None
        opened = False
        closed = False
        phase = 'device_unavailable'
        try:
            device, name, sample_rate = self.source.device()
            current.device_name, current.sample_rate = name, sample_rate
            phase = 'storage_write'
            path = self.repository.path(current.meeting_id, 'recording.wav')
            path.parent.mkdir(parents=True, exist_ok=False)
            writer = self.writer_factory(path, sample_rate)
            self.repository.update(current.meeting_id, deviceName=name, sampleRate=sample_rate, audioPath=f'meetings/{current.meeting_id}/recording.wav')
            phase = 'device_unavailable'
            if not current.stop.is_set():
                stream = self.source.stream(device, sample_rate, self.block_size, lambda *args: self.callback(current, *args))
                stream.start()
                opened = True
                self.repository.update(current.meeting_id, status='recording', startedAt=now())
                with self.lock:
                    if not current.stop.is_set():
                        current.state = 'recording'
            phase = 'storage_write'
            expected_sequence = 0
            expected_offset = 0
            while True:
                if current.stop.is_set() and not closed:
                    current.state = 'stopping'
                    if stream:
                        stream.stop()
                        stream.close()
                    closed = True
                    self.repository.update(current.meeting_id, status='stopping')
                try:
                    sequence, offset, pcm = current.chunks.get(timeout=0.05)
                except queue.Empty:
                    if closed:
                        break
                    if stream and (not stream.active or time.monotonic() - current.last_input > 3):
                        current.error_code = 'device_interrupted'
                        current.stop.set()
                    continue
                if sequence != expected_sequence or offset != expected_offset:
                    current.error_code = 'audio_overflow'
                    current.stop.set()
                writer.write(pcm)
                samples = array.array('h', pcm)
                level = math.sqrt(sum(sample * sample for sample in samples) / max(len(samples), 1)) / 32768
                current.frames = writer.frames
                current.input_level = min(1, level)
                expected_sequence += 1
                expected_offset += len(pcm) // 2
            writer.close()
            writer = None
            info = inspect_audio(path, sample_rate)
            final = self.repository.path(current.meeting_id, 'audio.wav')
            with self.lock:
                path.replace(final)
            phase = 'storage_commit'
            terminal = 'interrupted' if current.error_code else 'completed'
            self.repository.update(current.meeting_id, status=terminal, endedAt=now(), errorCode=current.error_code,
                                   audioPath=f'meetings/{current.meeting_id}/audio.wav', **info)
            current.state = terminal
        except Exception:
            current.error_code = current.error_code or phase
            current.stop.set()
            if stream and not closed:
                try:
                    stream.abort()
                    stream.close()
                except Exception:
                    pass
            if writer:
                try:
                    writer.close()
                except Exception:
                    pass
            info = None
            audio_path = None
            pending_info = None
            recovery_pending = False
            for filename in ('audio.wav', 'recording.wav'):
                try:
                    source = self.repository.path(current.meeting_id, filename)
                    if not source.exists():
                        continue
                    pending_info = inspect_recoverable_audio(source, current.sample_rate)
                    recovered = self.repository.path(current.meeting_id, 'recovered.wav')
                    info = recover_audio(source, recovered, current.sample_rate)
                    audio_path = f'meetings/{current.meeting_id}/recovered.wav'
                    break
                except OSError:
                    recovery_pending = True
                except Exception:
                    continue
            current.state = 'interrupted' if info else 'failed'
            metadata = info or pending_info or {'frames': 0, 'bytes': 0, 'durationMs': 0}
            if recovery_pending and not info:
                # A failed row with this target remains eligible for startup recovery.
                audio_path = f'meetings/{current.meeting_id}/recovered.wav'
            current.frames = metadata['frames']
            try:
                self.repository.update(current.meeting_id, status=current.state, endedAt=now(), errorCode=current.error_code,
                                       audioPath=audio_path, **metadata)
            except Exception:
                current.error_code = 'storage_commit'
        finally:
            current.finished.set()

    def shutdown(self, timeout=5):
        current = self.session
        if current and current.state in ACTIVE:
            self.stop(current.meeting_id, 'process_interrupted')
            return current.finished.wait(timeout)
        return True
