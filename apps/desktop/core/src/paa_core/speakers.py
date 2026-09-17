"""Meeting speaker tasks using the verified model bundled with the application."""
from __future__ import annotations

import threading

from .repository import DomainError
from .speaker_store import SpeakerStore
from .speaker_worker import bundled_model_path, run_worker, verified


class Speakers:
    def __init__(self, repo, transcription, runner=run_worker):
        self.repo, self.transcription, self.runner = repo, transcription, runner
        self.store = SpeakerStore(repo)
        self.lock = threading.RLock()
        self.path = bundled_model_path()
        self.cancelled = threading.Event()
        self.thread = None
        self.meeting_id = None
        self.closed = False
        self.progress = ''
        self.model = {'state': 'ready' if verified(self.path) else 'missing', 'error': None}
        if self.model['state'] == 'missing':
            self.model['error'] = '内置说话人模型缺失或损坏，请重新安装应用。'

    def active(self):
        return bool(self.thread and self.thread.is_alive())

    def status(self, meeting_id):
        with self.lock:
            result = self.store.status(meeting_id)
            return {**result, 'model': dict(self.model), 'progress': self.progress if self.meeting_id in (None, meeting_id) else ''}

    def _admit(self):
        if self.closed or self.active():
            raise DomainError('speaker_busy', '另一个说话人任务仍在处理，请稍后重试。')
        self.cancelled = threading.Event()
        self.progress = ''

    def start(self, meeting_id):
        with self.lock:
            self._admit()
            if self.model['state'] != 'ready' or not verified(self.path):
                self.model['state'] = 'missing'
                self.model['error'] = '内置说话人模型缺失或损坏，请重新安装应用。'
                raise DomainError('speaker_model', self.model['error'])
            if self.transcription.activity()['active']:
                raise DomainError('transcription_busy', '请等待当前转写结束后再区分说话人。')
            meeting = self.repo.get(meeting_id, internal=True)
            if meeting['durationMs'] > 10_800_000:
                raise DomainError('speaker_duration', '当前支持 3 小时以内的会议，原始文字不受影响。')
            meeting, generation = self.store.start(meeting_id)
            preference = self.transcription.model.status().get('device', 'gpu')
            self.meeting_id = meeting_id
            self.thread = threading.Thread(target=self._run, args=(meeting, generation, preference), name='speaker-inference', daemon=True)
            self.thread.start()
        return self.status(meeting_id)

    def _run(self, meeting, generation, preference):
        try:
            params = {'audio': str(self.repo.root / meeting['audioPath']), 'model': str(self.path), 'device': preference}
            result = self.runner(params, self.cancelled, lambda value: setattr(self, 'progress', value), max(180, meeting['durationMs'] / 1000 * 3))
            if not self.cancelled.is_set():
                self.store.finish(meeting['id'], generation, result['turns'], result['device'])
        except Exception as exc:
            self.store.stop(meeting['id'], None if self.cancelled.is_set() else str(exc) if isinstance(exc, DomainError) else '区分说话人失败，原文字已保留，可重试。')
        finally:
            if self.cancelled.is_set():
                self.store.stop(meeting['id'])
            self.progress = ''

    def pause(self):
        with self.lock:
            self.cancelled.set()

    def shutdown(self):
        self.closed = True
        self.pause()
        if self.thread:
            self.thread.join(12)
