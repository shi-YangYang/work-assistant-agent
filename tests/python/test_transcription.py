"""Deterministic fault controls; real Whisper evidence is a separate integration command."""
import io
import json
import multiprocessing
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from functools import partial
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/python'))
from paa_core.audio_store import AudioWriter
from paa_core.asr_worker import ASRWorker, DEFAULT_CONFIG, InferenceToken
from paa_core.model_manager import ModelManager, MODEL_ID, REVISION, verify_files
from paa_core.repository import Repository, DomainError
from paa_core.recorder import Recorder
from paa_core.transcript_store import TranscriptStore
from paa_core.transcription import Transcription, owned_segments, choose_boundary
from test_recording import FakeInput, wait_for


class ReadyModel:
    path = Path('unused-test-model')
    def status(self): return {'state': 'ready'}
    def shutdown(self): pass


class ControlledProvider:
    def __init__(self, path, _config): self.mode = str(path)
    def transcribe(self, pcm, rate):
        if self.mode == 'crash': os._exit(9)
        if self.mode == 'slow': time.sleep(2)
        return [{'start': 0.1, 'end': min(len(pcm) / (2 * rate), 0.3), 'text': '测试文字'}]


class HeldProvider:
    def __init__(self, _path, _config, entered, release):
        self.entered, self.release = entered, release
    def transcribe(self, _pcm, _rate):
        self.entered.release()
        if not self.release.acquire(timeout=10): raise AssertionError('Slow inference was not released')
        return [{'start': 0.1, 'end': 0.3, 'text': '测试文字'}]


class InlineWorker:
    def __init__(self): self.calls = []; self.fail = False
    def infer(self, path, pcm, rate, config, token=None):
        self.calls.append((len(pcm), rate))
        if self.fail: raise DomainError('test_failure', '可恢复的测试故障')
        return [{'start': 0.1, 'end': 0.3, 'text': '测试文字'}]
    def shutdown(self): pass
    def load(self, *args): pass


class TranscriptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='paa 转写 ')
        self.root = Path(self.temp.name)
        self.repo = Repository(self.root)
        self.recorder = Recorder(self.repo, FakeInput())
        self.workers = []
        self.services = []

    def tearDown(self):
        for service in self.services: service.shutdown()
        for worker in self.workers: worker.shutdown()
        self.recorder.shutdown()
        self.temp.cleanup()

    def audio(self, seconds=12.5, rate=16000):
        meeting_id = str(uuid.uuid4())
        self.repo.create(meeting_id, str(uuid.uuid4()))
        path = self.repo.path(meeting_id, 'audio.wav')
        path.parent.mkdir(parents=True)
        writer = AudioWriter(path, rate)
        writer.write(b'\x10\x10' * round(rate * seconds))
        writer.close()
        self.repo.update(meeting_id, status='completed', sampleRate=rate, frames=round(rate*seconds),
                         durationMs=round(seconds*1000), bytes=round(rate*seconds)*2,
                         audioPath=f'meetings/{meeting_id}/audio.wav')
        return meeting_id

    def service(self, worker=None):
        service = Transcription(self.repo, self.recorder, worker=worker or InlineWorker(), model=ReadyModel())
        self.services.append(service)
        return service

    def test_transaction_rolls_back_results_and_progress_and_replay_is_idempotent(self):
        mid = self.audio()
        store = TranscriptStore(self.repo)
        job = store.start(mid, MODEL_ID, REVISION, DEFAULT_CONFIG)
        chunk = {'startFrame': 0, 'endFrame': 160000, 'contextStart': 0, 'contextEnd': 192000}
        good = {'startMs': 100, 'endMs': 200, 'text': '一句话'}
        with self.assertRaises(KeyError): store.commit(job, chunk, [good, {}])
        self.assertEqual(store.job(mid)['processedFrames'], 0)
        self.assertEqual(store.page(mid)['segments'], [])
        self.assertTrue(store.commit(job, chunk, [good]))
        self.assertFalse(store.commit(job, chunk, [good]))
        self.assertEqual(len(store.page(mid)['segments']), 1)
        self.assertEqual(store.job(mid)['processedFrames'], 160000)

    def test_tail_restart_resume_and_completed_start_never_duplicate(self):
        mid = self.audio()
        service = self.service()
        service.start(mid)
        wait_for(lambda: service.status(mid)['state'] == 'completed')
        page = service.store.page(mid)
        self.assertEqual(service.status(mid)['processedMs'], 12500)
        self.assertEqual(len(page['segments']), 1)  # Second window's context-only word isn't duplicated.
        with self.repo.connect() as db:
            chunks = db.execute('SELECT startFrame,endFrame FROM audio_chunks ORDER BY sequence').fetchall()
            self.assertEqual([tuple(row) for row in chunks], [(0,160000),(160000,200000)])
        service.start(mid)
        self.assertEqual(service.store.page(mid), page)
        self.assertTrue(self.repo.get(mid)['audioAvailable'])

    def test_failure_keeps_checkpoint_and_retries_without_new_task(self):
        mid = self.audio(3)
        worker = InlineWorker(); worker.fail = True
        service = self.service(worker)
        service.start(mid)
        wait_for(lambda: service.status(mid)['state'] == 'failed')
        self.assertEqual(service.store.job(mid)['processedFrames'], 0)
        worker.fail = False
        service.start(mid)
        wait_for(lambda: service.status(mid)['state'] == 'completed')
        self.assertEqual(len(service.store.page(mid)['segments']), 1)
        self.assertEqual(service.store.job(mid)['nextChunk'], 1)

    def test_pause_after_reading_window_cannot_restart_the_selected_block(self):
        mid = self.audio(3)
        worker = InlineWorker()
        service = self.service(worker)
        selected, release, settled = threading.Event(), threading.Event(), threading.Event()
        read_window, wait = service.read_window, service.wake.wait

        def hold_window(*args):
            window = read_window(*args)
            selected.set()
            if not release.wait(3): raise AssertionError('Window was not released')
            return window

        def observe_idle(timeout):
            if release.is_set(): settled.set()
            return wait(timeout)

        service.read_window = hold_window
        service.wake.wait = observe_idle
        try:
            service.start(mid)
            self.assertTrue(selected.wait(3))
            service.pause()
            self.assertEqual(service.status(mid)['state'], 'paused')
            release.set()
            self.assertTrue(settled.wait(3))
            self.assertEqual(service.status(mid)['state'], 'paused')
            self.assertEqual(service.activity(), {'active': False})
            self.assertEqual(worker.calls, [])
            self.assertEqual(service.store.job(mid)['processedFrames'], 0)
            service.start(mid)
            wait_for(lambda: service.status(mid)['state'] == 'completed')
            self.assertEqual(len(worker.calls), 1)
            self.assertEqual(len(service.store.page(mid)['segments']), 1)
            self.assertEqual(service.store.job(mid)['nextChunk'], 1)
        finally:
            release.set()

    def test_immediate_continue_discards_the_previous_iteration_result_or_failure(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                mid = self.audio(3)
                entered, release = threading.Event(), threading.Event()
                resumed, finish = threading.Event(), threading.Event()

                class HeldWorker(InlineWorker):
                    def infer(self, path, pcm, rate, config, token=None):
                        self.calls.append((len(pcm), rate))
                        if len(self.calls) == 1:
                            entered.set()
                            if not release.wait(3): raise AssertionError('Old inference was not released')
                            if fail: raise DomainError('old_failure', '旧迭代故障')
                            return [{'start': 0.1, 'end': 0.3, 'text': '旧迭代'}]
                        resumed.set()
                        if not finish.wait(3): raise AssertionError('New inference was not released')
                        return [{'start': 0.1, 'end': 0.3, 'text': '继续后的文字'}]

                worker = HeldWorker()
                service = self.service(worker)
                try:
                    service.start(mid)
                    self.assertTrue(entered.wait(3))
                    service.pause()
                    service.start(mid)
                    release.set()
                    self.assertTrue(resumed.wait(3))
                    self.assertEqual(service.store.job(mid)['processedFrames'], 0)
                    self.assertEqual(service.store.page(mid)['segments'], [])
                    finish.set()
                    wait_for(lambda: service.status(mid)['state'] == 'completed')
                    self.assertEqual([s['text'] for s in service.store.page(mid)['segments']], ['继续后的文字'])
                    self.assertEqual(service.store.job(mid)['nextChunk'], 1)
                finally:
                    release.set()
                    finish.set()

    def test_restart_marks_active_jobs_paused_and_missing_audio_fails_on_continue(self):
        mid = self.audio(3)
        store = TranscriptStore(self.repo)
        store.start(mid, MODEL_ID, REVISION, DEFAULT_CONFIG)
        recovered = TranscriptStore(Repository(self.root))
        self.assertEqual(recovered.job(mid)['state'], 'paused')
        self.repo.path(mid, 'audio.wav').unlink()
        with self.assertRaises(DomainError): recovered.start(mid, MODEL_ID, REVISION, DEFAULT_CONFIG)
        self.assertEqual(recovered.job(mid)['state'], 'paused')

    def test_schema_one_migration_preserves_audio_and_failed_ddl_rolls_back(self):
        mid = self.audio(1)
        with self.repo.connect() as db:
            for table in ('meeting_summaries', 'summary_jobs', 'summary_attempts'): db.execute('DROP TABLE ' + table)
            db.execute('DROP TABLE transcript_segments'); db.execute('DROP TABLE audio_chunks')
            db.execute('DROP TABLE transcription_jobs'); db.execute('PRAGMA user_version=1')
        def broken(db):
            db.execute('CREATE TABLE partial_migration (id TEXT)')
            raise sqlite3.OperationalError('Injected DDL failure')
        with patch('paa_core.transcript_store.migrate', broken), self.assertRaises(sqlite3.OperationalError):
            Repository(self.root)
        with self.repo.connect() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='partial_migration'").fetchone())
        upgraded = Repository(self.root)
        self.assertTrue(upgraded.get(mid)['audioAvailable'])
        self.assertIsNone(TranscriptStore(upgraded).job(mid))
        self.assertTrue((self.root / 'meetings.schema1.backup.sqlite3').exists())

    def test_backup_failure_removes_staging_and_busy_database_has_deadline(self):
        class BrokenBackup:
            def backup(self, target, **kwargs):
                target.execute('CREATE TABLE incomplete (id TEXT)')
                raise sqlite3.OperationalError('Injected backup failure')
        with self.assertRaises(sqlite3.OperationalError): self.repo.backup_schema(BrokenBackup(), 1)
        self.assertFalse((self.root/'meetings.schema1.backup.staging').exists())
        self.assertFalse((self.root/'meetings.schema1.backup.sqlite3').exists())
        lock=sqlite3.connect(self.repo.database)
        try:
            lock.execute('BEGIN EXCLUSIVE')
            with self.repo.connect() as source:
                started=time.monotonic()
                with self.assertRaises(DomainError): self.repo.backup_schema(source, 1)
                self.assertLess(time.monotonic()-started,3)
        finally: lock.rollback();lock.close()
        self.assertFalse((self.root/'meetings.schema1.backup.staging').exists())
        with self.repo.connect() as source: self.repo.backup_schema(source, 1)
        self.assertTrue((self.root/'meetings.schema1.backup.sqlite3').exists())

    def test_worker_crash_and_timeout_are_bounded_and_leave_no_child(self):
        for mode, timeout in [('crash', 5), ('slow', 0.3)]:
            worker = ASRWorker(ControlledProvider, timeout=timeout); self.workers.append(worker)
            if mode == 'slow':
                worker.timeout = 5; worker.load(mode); worker.timeout = timeout
            with self.assertRaises(DomainError): worker.infer(mode, b'\0\0'*16000, 16000, DEFAULT_CONFIG)
            self.assertIsNone(worker.process)

    def test_cancelled_worker_generation_cannot_dispatch_after_a_continue(self):
        worker = ASRWorker(ControlledProvider); self.workers.append(worker)
        worker.load('ready')
        token = InferenceToken()
        selected, release = threading.Event(), threading.Event()
        request, errors = worker._request, []

        def hold_dispatch(command, operation_token=None):
            if command['op'] == 'infer':
                selected.set()
                if not release.wait(3): raise AssertionError('Dispatch was not released')
            return request(command, operation_token)

        def infer():
            try: worker.infer('ready', b'\0\0' * 16000, 16000, DEFAULT_CONFIG, token)
            except Exception as exc: errors.append(exc)

        with patch.object(worker, '_request', hold_dispatch), patch.object(worker.connection, 'send', wraps=worker.connection.send) as send:
            thread = threading.Thread(target=infer)
            thread.start()
            try:
                self.assertTrue(selected.wait(3))
                token.cancel()
                next_token = InferenceToken()
                release.set()
                thread.join(timeout=3)
                self.assertFalse(thread.is_alive())
                self.assertEqual(len(errors), 1)
                self.assertIsInstance(errors[0], DomainError)
                send.assert_not_called()
                self.assertEqual(worker.infer('ready', b'\0\0' * 16000, 16000, DEFAULT_CONFIG, next_token)[0]['text'], '测试文字')
                self.assertEqual([call.args[0]['op'] for call in send.call_args_list], ['infer'])
            finally:
                release.set()
                thread.join(timeout=3)

    def test_cancelling_running_worker_is_prompt_and_reclaims_the_child(self):
        worker = ASRWorker(ControlledProvider); self.workers.append(worker)
        worker.load('slow')
        token = InferenceToken()
        dispatched, errors = threading.Event(), []
        send = worker.connection.send

        def observe_send(command):
            send(command)
            if command['op'] == 'infer': dispatched.set()

        def infer():
            try: worker.infer('slow', b'\0\0' * 16000, 16000, DEFAULT_CONFIG, token)
            except Exception as exc: errors.append(exc)

        with patch.object(worker.connection, 'send', observe_send):
            thread = threading.Thread(target=infer)
            thread.start()
            try:
                self.assertTrue(dispatched.wait(3))
                started = time.monotonic()
                token.cancel()
                self.assertLess(time.monotonic() - started, .1)
                thread.join(timeout=1)
                self.assertFalse(thread.is_alive())
                self.assertEqual(len(errors), 1)
                self.assertIsInstance(errors[0], DomainError)
                self.assertIsNone(worker.process)
            finally:
                token.cancel()
                thread.join(timeout=3)

    def test_overlap_time_mapping_silence_and_boundary_do_not_repeat_words(self):
        words = [{'start': 1.9, 'end': 2.1, 'text':'边界'}, {'start': 2.2,'end':2.5,'text':'下一句'}]
        first = {'startFrame':0,'endFrame':480000,'contextStart':0,'contextEnd':576000}
        second = {'startFrame':480000,'endFrame':960000,'contextStart':384000,'contextEnd':1056000}
        self.assertEqual(owned_segments([], first, 48000), [])
        self.assertEqual(''.join(x['text'] for x in owned_segments(words, second, 48000)), '边界下一句')
        self.assertEqual(owned_segments(words, second, 48000)[0]['startMs'],10000)
        pcm = b'\x10\x10' * (16000*7) + b'\0\0' * (16000*3)
        self.assertEqual(choose_boundary(pcm,16000,160000),136000)

    def test_pagination_is_bounded_and_ordered(self):
        mid = self.audio(100)
        store = TranscriptStore(self.repo); job=store.start(mid,MODEL_ID,REVISION,DEFAULT_CONFIG)
        chunk={'startFrame':0,'endFrame':160000,'contextStart':0,'contextEnd':160000}
        store.commit(job,chunk,[{'startMs':i,'endMs':i+1,'text':'文字'*150} for i in range(60)])
        page=store.page(mid)
        self.assertEqual(len(page['segments']),50);self.assertTrue(page['hasMore'])
        self.assertLess(len(json.dumps(page,ensure_ascii=False).encode()),65536)
        self.assertEqual(len(store.page(mid,page['nextCursor'])['segments']),10)

    def test_slow_worker_does_not_block_recording_controls_or_frame_growth(self):
        class DrivenStream:
            active=False
            def __init__(self,callback): self.callback=callback
            def start(self): self.active=True
            def stop(self): self.active=False
            close=stop
            abort=stop
        class DrivenInput(FakeInput):
            def stream(self,_device,_rate,_block,callback):
                self.capture=DrivenStream(callback)
                return self.capture

        source=DrivenInput()
        self.recorder=Recorder(self.repo,source)
        ctx=multiprocessing.get_context('spawn')
        # Event.set() waits for every registered sleeper to acknowledge waking.
        # Cancellation kills the waiting child, so cleanup must never require its reply.
        entered,release=ctx.Semaphore(0),ctx.Semaphore(0)
        worker=ASRWorker(partial(HeldProvider,entered=entered,release=release));self.workers.append(worker)
        model=ReadyModel()
        service=Transcription(self.repo,self.recorder,worker=worker,model=model);self.services.append(service)
        mid=self.recorder.start(str(uuid.uuid4()))['meetingId']
        wait_for(lambda:self.recorder.status()['state']=='recording')

        def feed_frames(frames):
            # Publish exact input through the real bounded callback/writer chain.
            # Timer coalescing must not decide whether a full ASR window exists.
            while frames:
                batch=min(frames,self.recorder.block_size*32)
                target=self.recorder.session.frames+batch
                remaining=batch
                while remaining:
                    count=min(remaining,self.recorder.block_size)
                    source.capture.callback(b'\x10\x10'*count,count,None,False)
                    remaining-=count
                wait_for(lambda:self.recorder.session.frames==target)
                self.assertEqual(self.recorder.status()['state'],'recording')
                frames-=batch

        try:
            required_frames=round((DEFAULT_CONFIG['chunkSeconds']+DEFAULT_CONFIG['contextSeconds'])*self.recorder.session.sample_rate)
            feed_frames(required_frames)
            service.start(mid)
            self.assertTrue(entered.acquire(timeout=6), {'transcription':service.status(mid),'recording':self.recorder.status()})
            self.assertEqual(service.status(mid)['state'],'running')
            initial=self.recorder.session.frames
            feed_frames(self.recorder.block_size*4)
            self.assertGreater(self.recorder.session.frames,initial)
            self.assertGreater(service.status(mid)['pendingMs'],0)
            self.assertFalse(release.acquire(block=False))
            self.assertEqual(service.status(mid)['processedMs'],0)
            start=time.monotonic();self.recorder.stop(mid);self.assertLess(time.monotonic()-start,.1)
            wait_for(lambda:self.recorder.session.finished.is_set())
            self.assertTrue(self.repo.get(mid)['audioAvailable'])
            self.assertLessEqual(self.recorder.session.chunks.qsize(),64)
            service.pause()
            self.assertEqual(service.status(mid)['state'],'paused')
            # Exercise cleanup after cancellation has actually reclaimed the waiter.
            wait_for(lambda:worker.process is None)
        finally:
            release.release()

    def test_corrupt_model_is_not_ready_and_download_cancel_and_retry_are_atomic(self):
        import hashlib
        data=b'controlled model fixture';files={'model.bin':(len(data),hashlib.sha256(data).hexdigest())}
        class Response(io.BytesIO): pass
        class Opener:
            def open(self,*args,**kwargs):return Response(data)
        model=ModelManager(self.root,InlineWorker())
        with patch('paa_core.model_manager.FILES',files), patch('paa_core.model_manager.urllib.request.build_opener',return_value=Opener()):
            model.download();wait_for(lambda:model.status()['state']=='ready')
            self.assertFalse(model.staging.exists())
            verify_files(model.path)
            (model.path/'model.bin').write_bytes(b'bad')
            restarted=ModelManager(self.root,InlineWorker())
            wait_for(lambda:restarted.status()['state']=='error')
            class SlowResponse(Response):
                def read(self,size):time.sleep(.2);return super().read(size)
            class SlowOpener:
                def open(self,*args,**kwargs):return SlowResponse(data)
            with patch('paa_core.model_manager.urllib.request.build_opener',return_value=SlowOpener()):
                restarted.download();restarted.cancel();wait_for(lambda:restarted.status()['state']=='missing')
            restarted.download();wait_for(lambda:restarted.status()['state']=='ready')
            self.assertFalse(restarted.staging.exists())
            restarted.shutdown()
        model.shutdown()
