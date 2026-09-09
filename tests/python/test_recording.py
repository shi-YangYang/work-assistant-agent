import array
import errno
import json
import math
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import uuid
import wave
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/python'))
from paa_core.audio_store import AudioWriter
from paa_core.protocol import CoreService, handle
from paa_core.recorder import Recorder
from paa_core.repository import DomainError, Repository


class FakeStream:
    """Synthetic deterministic PCM only; never presented as device evidence."""
    def __init__(self, callback, count=6, overflow=False):
        self.callback, self.count, self.overflow = callback, count, overflow
        self.active = False
        self.done = threading.Event()

    def start(self):
        self.active = True
        def produce():
            for _ in range(self.count):
                if self.done.is_set():
                    break
                self.callback(array.array('h', [1000, -1000] * 128).tobytes(), 256, None, False)
                time.sleep(0.005)
            if self.overflow:
                self.callback(b'', 0, None, True)
        threading.Thread(target=produce, daemon=True).start()

    def stop(self):
        self.done.set()
        self.active = False

    close = stop
    abort = stop


class FakeInput:
    def __init__(self, overflow=False, count=6):
        self.overflow, self.count = overflow, count
    def device(self):
        return 0, '合成输入（测试）', 48000
    def stream(self, _device, _rate, _block, callback):
        return FakeStream(callback, self.count, self.overflow)


def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError('Timed out waiting for recorder')


@contextmanager
def recovery_disk_full():
    original_open = Path.open
    def failing_open(path, mode='r', *args, **kwargs):
        if path.name == 'recovered.recovering' and mode == 'wb':
            raise OSError(errno.ENOSPC, 'No space for recovery copy')
        return original_open(path, mode, *args, **kwargs)
    with patch.object(Path, 'open', failing_open):
        yield


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='paa 会议 ')
        self.root = Path(self.temp.name)
        self.repo = Repository(self.root)
        self.recorder = Recorder(self.repo, FakeInput())
    def tearDown(self):
        self.recorder.shutdown()
        self.temp.cleanup()
    def start(self):
        operation = str(uuid.uuid4())
        result = self.recorder.start(operation)
        wait_for(lambda: self.recorder.status()['elapsedMs'] > 0)
        return operation, result['meetingId']
    def finish(self, meeting_id):
        self.recorder.stop(meeting_id)
        wait_for(lambda: self.recorder.session.finished.is_set())
        return self.repo.get(meeting_id, internal=True)

    def test_idempotent_capture_frames_level_stop_and_restart_history(self):
        operation, meeting_id = self.start()
        self.assertEqual(self.recorder.start(operation)['meetingId'], meeting_id)
        self.assertEqual(self.recorder.start(str(uuid.uuid4()))['meetingId'], meeting_id)
        wait_for(lambda: self.recorder.session.frames == 1536)
        self.assertAlmostEqual(self.recorder.status()['inputLevel'], 1000 / 32768)
        row = self.finish(meeting_id)
        self.assertEqual(row['status'], 'completed')
        self.assertEqual(row['frames'], 1536)
        self.assertEqual(row['durationMs'], 32)
        self.assertEqual(self.recorder.stop(meeting_id)['state'], 'completed')
        restored = Repository(self.root)
        self.assertTrue(restored.get(meeting_id)['audioAvailable'])
        self.assertEqual(restored.list()['meetings'][0]['id'], meeting_id)
        self.assertEqual(Recorder(restored, FakeInput()).start(operation)['meetingId'], meeting_id)
        with wave.open(str(self.root / row['audioPath'])) as audio:
            self.assertEqual(audio.readframes(1536), array.array('h', [1000, -1000] * 768).tobytes())

    def test_device_denied_never_claims_recording(self):
        class Denied(FakeInput):
            def device(self):
                raise OSError('Denied')
        self.recorder = Recorder(self.repo, Denied())
        result = self.recorder.start(str(uuid.uuid4()))
        wait_for(lambda: self.recorder.session.finished.is_set())
        self.assertEqual(self.recorder.status()['state'], 'failed')
        self.assertFalse(self.repo.get(result['meetingId'])['audioAvailable'])

    def test_driver_overflow_marks_partial_recording(self):
        self.recorder = Recorder(self.repo, FakeInput(overflow=True))
        _, meeting_id = self.start()
        wait_for(lambda: self.recorder.session.finished.is_set())
        row = self.repo.get(meeting_id)
        self.assertEqual(row['status'], 'interrupted')
        self.assertEqual(row['errorCode'], 'audio_overflow')
        self.assertTrue(row['audioAvailable'])

    def test_bounded_queue_overflow_is_explicit(self):
        self.recorder = Recorder(self.repo, FakeInput(), queue_size=1)
        from paa_core.recorder import Session
        import queue
        session = Session(str(uuid.uuid4()), chunks=queue.Queue(maxsize=1))
        self.recorder.callback(session, b'\0\0' * 256, 256, None, False)
        self.recorder.callback(session, b'\0\0' * 256, 256, None, False)
        self.assertEqual(session.chunks.qsize(), 1)
        self.assertEqual(session.error_code, 'audio_overflow')
        self.assertTrue(session.stop.is_set())

    def test_write_failure_preserves_complete_frames(self):
        class FailingWriter(AudioWriter):
            def write(self, pcm):
                if self.frames:
                    raise OSError('Disk full')
                super().write(pcm)
        self.recorder = Recorder(self.repo, FakeInput(), writer_factory=FailingWriter)
        result = self.recorder.start(str(uuid.uuid4()))
        wait_for(lambda: self.recorder.session.finished.is_set())
        row = self.repo.get(result['meetingId'])
        self.assertEqual(row['status'], 'interrupted')
        self.assertEqual(row['frames'], 256)
        self.assertTrue(row['audioAvailable'])
        self.assertTrue(self.repo.path(row['id'], 'recording.wav').exists())

    def assert_pending_recovery(self, repository, meeting_id, frames, error_code):
        row = repository.get(meeting_id, internal=True)
        self.assertEqual(row['status'], 'failed')
        self.assertEqual(row['errorCode'], error_code)
        self.assertEqual(row['frames'], frames)
        self.assertEqual(row['bytes'], frames * 2)
        self.assertEqual(row['durationMs'], round(frames * 1000 / 48000))
        self.assertFalse(row['audioAvailable'])
        self.assertIn('重新连接', row['audioError'])
        self.assertNotIn('audioPath', row)
        with repository.connect() as db:
            target = db.execute('SELECT audioPath FROM meetings WHERE id=?', (meeting_id,)).fetchone()[0]
        self.assertEqual(target, f'meetings/{meeting_id}/recovered.wav')
        return row

    def assert_recovered_pcm(self, meeting_id, pcm, error_code):
        row = Repository(self.root).get(meeting_id, internal=True)
        self.assertEqual(row['status'], 'interrupted')
        self.assertEqual(row['errorCode'], error_code)
        self.assertEqual(row['frames'], len(pcm) // 2)
        self.assertEqual(row['bytes'], len(pcm))
        self.assertEqual(row['durationMs'], round(len(pcm) * 500 / 48000))
        self.assertTrue(row['audioAvailable'])
        self.assertIsNone(row['audioError'])
        self.assertEqual(row['audioPath'], f'meetings/{meeting_id}/recovered.wav')
        path = self.root / row['audioPath']
        self.assertEqual(path.stat().st_size, 44 + row['bytes'])
        with wave.open(str(path)) as audio:
            self.assertEqual((audio.getnchannels(), audio.getsampwidth(), audio.getframerate()), (1, 2, 48000))
            self.assertEqual(audio.readframes(row['frames'] + 1), pcm)

    def test_write_and_recovery_copy_failure_retries_after_storage_recovers(self):
        class FailingWriter(AudioWriter):
            def write(self, pcm):
                if self.frames:
                    raise OSError(errno.ENOSPC, 'Disk full')
                super().write(pcm)
        self.recorder = Recorder(self.repo, FakeInput(), writer_factory=FailingWriter)
        with recovery_disk_full():
            result = self.recorder.start(str(uuid.uuid4()))
            self.assertTrue(self.recorder.session.finished.wait(3))
            meeting_id = result['meetingId']
            before = self.assert_pending_recovery(self.repo, meeting_id, 256, 'storage_write')
            self.assertEqual(self.recorder.status()['state'], 'failed')
            self.assertEqual(self.recorder.session.frames, 256)
            source = self.repo.path(meeting_id, 'recording.wav')
            original = source.read_bytes()
            retried = self.assert_pending_recovery(Repository(self.root), meeting_id, 256, 'storage_write')
            self.assertEqual(retried['endedAt'], before['endedAt'])
        self.assert_recovered_pcm(meeting_id, array.array('h', [1000, -1000] * 128).tobytes(), 'storage_write')
        self.assertEqual(source.read_bytes(), original)

    def test_startup_recovery_copy_failure_retains_unadvertised_frames_for_retry(self):
        meeting_id = str(uuid.uuid4())
        self.repo.create(meeting_id, str(uuid.uuid4()))
        self.repo.update(meeting_id, status='recording', audioPath=f'meetings/{meeting_id}/recording.wav')
        source = self.repo.path(meeting_id, 'recording.wav')
        source.parent.mkdir(parents=True)
        writer = AudioWriter(source, 48000)
        writer.write(b'\0\0' * 128)
        writer.close()
        with source.open('ab') as audio:
            audio.write(b'\1\0' * 64 + b'\1')
        original = source.read_bytes()
        with recovery_disk_full():
            first = self.assert_pending_recovery(Repository(self.root), meeting_id, 192, 'process_interrupted')
            second = self.assert_pending_recovery(Repository(self.root), meeting_id, 192, 'process_interrupted')
            self.assertEqual(second['endedAt'], first['endedAt'])
        self.assert_recovered_pcm(meeting_id, b'\0\0' * 128 + b'\1\0' * 64, 'process_interrupted')
        self.assertEqual(source.read_bytes(), original)

    def test_empty_or_invalid_audio_is_not_marked_pending_or_playable(self):
        for invalid in (False, True):
            with self.subTest(invalid_header=invalid):
                meeting_id = str(uuid.uuid4())
                self.repo.create(meeting_id, str(uuid.uuid4()))
                path = self.repo.path(meeting_id, 'recording.wav')
                path.parent.mkdir(parents=True)
                if invalid:
                    path.write_bytes(b'invalid WAV')
                else:
                    AudioWriter(path, 48000).close()
                original = path.read_bytes()
                restored = Repository(self.root)
                row = restored.get(meeting_id)
                self.assertEqual(row['status'], 'failed')
                self.assertEqual(row['frames'], 0)
                self.assertFalse(row['audioAvailable'])
                with restored.connect() as db:
                    self.assertIsNone(db.execute('SELECT audioPath FROM meetings WHERE id=?', (meeting_id,)).fetchone()[0])
                self.assertEqual(path.read_bytes(), original)

    def test_crash_recovery_retains_unadvertised_frames_and_original(self):
        meeting_id = str(uuid.uuid4())
        self.repo.create(meeting_id, str(uuid.uuid4()))
        self.repo.update(meeting_id, status='recording')
        path = self.repo.path(meeting_id, 'recording.wav')
        path.parent.mkdir(parents=True)
        writer = AudioWriter(path, 48000)
        writer.write(b'\0\0' * 128)
        writer.close()
        with path.open('ab') as audio:
            audio.write(b'\1\0' * 64 + b'\1')
        restored = Repository(self.root).get(meeting_id)
        self.assertEqual(restored['status'], 'interrupted')
        self.assertEqual(restored['frames'], 192)
        self.assertTrue(restored['audioAvailable'])
        self.assertEqual(path.stat().st_size, 44 + 384 + 1)

    def test_missing_and_path_escape_files_are_not_playable(self):
        _, meeting_id = self.start()
        row = self.finish(meeting_id)
        self.repo.update(meeting_id, audioPath='../outside.wav')
        self.assertFalse(self.repo.get(meeting_id)['audioAvailable'])
        self.repo.update(meeting_id, audioPath=row['audioPath'])
        self.repo.path(meeting_id, 'audio.wav').rename(self.root / 'moved.wav')
        self.assertFalse(self.repo.get(meeting_id)['audioAvailable'])
        self.assertIsNotNone(self.repo.get(meeting_id)['audioError'])

    def test_schema_conflict_and_database_lock_preserve_data(self):
        with sqlite3.connect(self.repo.database) as db:
            db.execute('PRAGMA user_version=99')
        with self.assertRaises(DomainError):
            Repository(self.root)
        with sqlite3.connect(self.repo.database) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 99)
            db.execute('PRAGMA user_version=1')
            db.execute('BEGIN EXCLUSIVE')
            with self.assertRaises(sqlite3.OperationalError):
                self.repo.create(str(uuid.uuid4()), str(uuid.uuid4()))

    def test_controls_do_not_wait_for_device_open_or_finalization(self):
        gate = threading.Event()
        class SlowInput(FakeInput):
            def device(self):
                gate.wait(2)
                return super().device()
        service = CoreService(self.root, SlowInput())
        start = time.monotonic()
        result, _ = handle({'id': 's', 'method': 'recording.start', 'params': {'operationId': str(uuid.uuid4())}}, service)
        self.assertLess(time.monotonic() - start, 0.2)
        meeting_id = result['result']['meetingId']
        response, stopping = handle({'id': 'q', 'method': 'shutdown'}, service)
        self.assertFalse(stopping)
        self.assertEqual(response['error']['code'], 'recording_active')
        handle({'id': 'x', 'method': 'recording.stop', 'params': {'meetingId': meeting_id}}, service)
        gate.set()
        service.recorder.shutdown()

    def test_suspend_preserves_partial_and_final_commit_failure_is_visible(self):
        _, meeting_id = self.start()
        self.recorder.stop(meeting_id, 'system_suspend')
        wait_for(lambda: self.recorder.session.finished.is_set())
        self.assertEqual(self.repo.get(meeting_id)['status'], 'interrupted')
        self.assertEqual(self.repo.get(meeting_id)['errorCode'], 'system_suspend')
        self.recorder = Recorder(self.repo, FakeInput())
        _, meeting_id = self.start()
        original = self.repo.update
        def failing(meeting_id, **fields):
            if fields.get('status') in ('completed', 'interrupted', 'failed'):
                raise sqlite3.OperationalError('Database locked')
            return original(meeting_id, **fields)
        self.repo.update = failing
        self.finish(meeting_id)
        self.assertEqual(self.recorder.status()['error']['code'], 'storage_commit')
        self.repo.update = original
        recovered = Repository(self.root).get(meeting_id)
        self.assertEqual(recovered['status'], 'interrupted')
        self.assertTrue(recovered['audioAvailable'])


if __name__ == '__main__':
    unittest.main()
