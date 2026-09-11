"""Disk-backed scheduling: one bounded window in flight, live recording takes priority."""
from __future__ import annotations

import array
import math
import sys
import threading
import wave

from .asr_worker import ASRWorker, DEFAULT_CONFIG, InferenceToken
from .model_manager import MODEL_ID, REVISION, ModelManager
from .repository import ACTIVE, DomainError
from .transcript_store import JOB_ACTIVE, TranscriptStore


def choose_boundary(pcm, sample_rate, nominal_frames):
    """Prefer a quiet boundary near the target without waiting for a whole utterance.

    The valid range remains continuous. This does not drop silence or infer text from energy.
    VAD still runs in the worker; this bounded scan just avoids cutting through words.
    """
    samples = array.array('h', pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    step = max(1, sample_rate // 50)
    earliest = max(5 * sample_rate, nominal_frames - 5 * sample_rate)
    quiet_start = None
    candidates = []
    for offset in range(0, min(len(samples), nominal_frames), step):
        block = samples[offset:offset + step]
        quiet = bool(block) and sum(x * x for x in block) / len(block) < 200 ** 2
        if quiet and quiet_start is None:
            quiet_start = offset
        if not quiet and quiet_start is not None:
            if offset - quiet_start >= sample_rate * 0.3:
                midpoint = (quiet_start + offset) // 2
                if midpoint >= earliest:
                    candidates.append(midpoint)
            quiet_start = None
    if quiet_start is not None and nominal_frames - quiet_start >= sample_rate * 0.3:
        midpoint = (quiet_start + nominal_frames) // 2
        if midpoint >= earliest:
            candidates.append(midpoint)
    return candidates[-1] if candidates else nominal_frames


def owned_segments(words, chunk, sample_rate):
    """Word midpoint assigns overlap once; context is never persisted as duplicate speech."""
    start = chunk['startFrame'] * 1000 / sample_rate
    end = chunk['endFrame'] * 1000 / sample_rate
    offset = chunk['contextStart'] * 1000 / sample_rate
    segments = []
    for word in words:
        left, right = offset + word['start'] * 1000, offset + word['end'] * 1000
        if not all(math.isfinite(value) for value in (left, right)) or right < left:
            raise ValueError('Invalid ASR timestamps')
        if not start <= (left + right) / 2 < end or not word['text'].strip():
            continue
        left, right = max(round(start), round(left)), min(round(end), round(right))
        if segments and left - segments[-1]['endMs'] < 1000 and len(segments[-1]['text'] + word['text']) <= 300:
            segments[-1]['text'] += word['text']
            segments[-1]['endMs'] = max(segments[-1]['endMs'], right)
        else:
            segments.append({'startMs': left, 'endMs': right, 'text': word['text']})
    return segments


class Transcription:
    def __init__(self, repository, recorder, worker=None, model=None, config=None):
        self.repo, self.recorder = repository, recorder
        self.store = TranscriptStore(repository)
        self.worker = worker or ASRWorker()
        self.model = model or ModelManager(repository.root, self.worker)
        self.config = dict(config or DEFAULT_CONFIG)
        if not 5 <= self.config['chunkSeconds'] <= 15:
            raise ValueError('Chunk size must be between 5 and 15 seconds')
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.pausing = threading.Event()
        self.control_lock = threading.Lock()
        self.token = InferenceToken()
        self.failure = None
        self.thread = threading.Thread(target=self.run, name='transcription-scheduler', daemon=True)
        self.thread.start()

    def start(self, meeting_id):
        if self.model.status()['state'] != 'ready':
            raise DomainError('model_not_ready', '请先在设置中下载并准备本地转写模型。')
        with self.control_lock:
            if self.stop_event.is_set():
                raise DomainError('transcription_paused', '转写已暂停，可以稍后继续。')
            current = self.store.job(meeting_id)
            if current and (current['modelId'] != MODEL_ID or current['revision'] != REVISION):
                raise DomainError('model_mismatch', '此任务需要的模型版本不可用，请保留数据并联系维护者。')
            self.store.start(meeting_id, MODEL_ID, REVISION, self.config)
            if self.pausing.is_set():
                self.token = InferenceToken()
                self.pausing.clear()
            if self.failure and self.failure[0] == meeting_id:
                self.failure = None
        self.wake.set()
        return self.status(meeting_id)

    def auto_start(self, meeting_id):
        if self.model.status()['state'] == 'ready':
            try:
                self.start(meeting_id)
            except DomainError:
                pass

    def status(self, meeting_id):
        meeting = self.repo.get(meeting_id)
        recording = self.recorder.status()
        elapsed = recording['elapsedMs'] if recording['meetingId'] == meeting_id and recording['state'] in ACTIVE else meeting['durationMs']
        job = self.store.job(meeting_id)
        processed = round(job['processedFrames'] * 1000 / meeting['sampleRate']) if job else 0
        return {'meetingId': meeting_id, 'state': job['state'] if job else 'not_started',
                'processedMs': processed, 'audioMs': elapsed, 'pendingMs': max(0, elapsed - processed),
                'targetFrames': job['targetFrames'] if job else None,
                'error': self.failure[1] if self.failure and self.failure[0] == meeting_id else (job['error'] if job else None),
                'sourceIncomplete': meeting['status'] == 'interrupted'}

    def activity(self):
        return {'active': bool(self.store.pending())}

    def read_window(self, meeting_id, job):
        # Recorder's final rename uses this same lock. Never retain a WAV handle during inference.
        with self.recorder.lock:
            meeting = self.repo.get(meeting_id, internal=True)
            current = self.recorder.session
            live = current is not None and current.meeting_id == meeting_id and current.state in ACTIVE
            if live:
                if current.state not in ('recording', 'paused'):
                    return None
                available, rate = current.frames, current.sample_rate
                path = self.repo.path(meeting_id, 'recording.wav')
                target = None
            else:
                if meeting['status'] in ACTIVE:
                    return None
                if not meeting['audioAvailable']:
                    raise DomainError('audio_unavailable', meeting['audioError'] or '录音无法读取，请检查存储后继续。')
                available, rate = meeting['frames'], meeting['sampleRate']
                path = self.repo.path(meeting_id, meeting['audioPath'].split('/')[-1])
                target = available
            start = job['processedFrames']
            if start > available:
                raise DomainError('audio_range', '恢复后的音频短于已处理范围，请保留数据并检查录音。')
            size = round(job['config']['chunkSeconds'] * rate)
            context = round(job['config']['contextSeconds'] * rate)
            end = min(start + size, available)
            if live and available < start + size + context:
                return None
            if start == available:
                return None if live else (None, b'', rate, available)
            chunk = {'startFrame': start, 'endFrame': end,
                     'contextStart': max(0, start - context), 'contextEnd': min(available, end + context)}
            with wave.open(str(path), 'rb') as wav:
                if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != rate:
                    raise DomainError('audio_format', '录音格式与记录不一致，请保留原文件。')
                wav.setpos(chunk['contextStart'])
                pcm = wav.readframes(chunk['contextEnd'] - chunk['contextStart'])
            if len(pcm) != (chunk['contextEnd'] - chunk['contextStart']) * 2:
                raise DomainError('audio_short_read', '录音未能完整读取，请检查文件后继续。')
            if end < available and end - start == size:
                relative_start = start - chunk['contextStart']
                boundary = choose_boundary(pcm[relative_start * 2:], rate, size)
                chunk['endFrame'] = start + boundary
                chunk['contextEnd'] = min(available, chunk['endFrame'] + context)
                pcm = pcm[:(chunk['contextEnd'] - chunk['contextStart']) * 2]
            return chunk, pcm, rate, target

    def run(self):
        while not self.stop_event.is_set():
            worked = False
            meeting_id = None
            token = None
            try:
                with self.control_lock:
                    token = self.token
                    if self.failure:
                        self.store.state(self.failure[0], 'failed', self.failure[1])
                        self.failure = None
                    pending = self.store.pending() if self.current(token) else []
                live_id = self.recorder.status()['meetingId']
                pending.sort(key=lambda value: value != live_id)
                for meeting_id in pending:
                    with self.control_lock:
                        if not self.current(token):
                            break
                        job = self.store.job(meeting_id)
                        if not job or job['state'] not in JOB_ACTIVE:
                            continue
                    window = self.read_window(meeting_id, job)
                    if window is None:
                        continue
                    if self.model.status()['state'] != 'ready':
                        raise DomainError('model_not_ready', '模型尚未就绪，请在设置中准备后继续转写。')
                    chunk, pcm, rate, target = window
                    # Reading and inference do not hold the control lock. Claiming a
                    # window, committing it and pausing share one short state boundary.
                    with self.control_lock:
                        if not self.current(token):
                            break
                        if chunk is None:
                            self.store.state(meeting_id, 'completed', target=target)
                            continue
                        self.store.state(meeting_id, 'draining' if target is not None else 'running', target=target)
                    words = self.worker.infer(self.model.path, pcm, rate, job['config'], token=token)
                    segments = owned_segments(words, chunk, rate)
                    with self.control_lock:
                        if self.current(token):
                            self.store.commit(job, chunk, segments, target)
                    worked = True
                    break
            except Exception as exc:
                with self.control_lock:
                    if meeting_id and self.current(token):
                        try:
                            self.store.state(meeting_id, 'failed', str(exc) if isinstance(exc, DomainError) else '转写保存失败，请检查存储空间后继续；原始录音和已提交文字保留。')
                        except Exception:
                            # SQLite may be locked; retry recording the failure after a bounded wait.
                            self.failure = (meeting_id, '转写进度暂时无法保存，请排除数据库占用后继续；原始音频保留。')
            if not worked:
                self.wake.wait(0.3)
                self.wake.clear()

    def current(self, token):
        # Caller holds control_lock; a continue request never reuses a cancelled token.
        return token is self.token and not self.stop_event.is_set() and not self.pausing.is_set()

    def pause(self):
        with self.control_lock:
            self.token.cancel()
            self.pausing.set()
            self.failure = None
            if hasattr(self.worker, 'interrupt'):
                self.worker.interrupt()
            self.store.pause()
        return {'active': False}

    def shutdown(self):
        with self.control_lock:
            self.stop_event.set()
            self.token.cancel()
        self.wake.set()
        self.model.shutdown()
        self.worker.shutdown()
        self.thread.join(timeout=3)
        self.store.pause()
