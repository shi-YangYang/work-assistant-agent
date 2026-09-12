"""Meeting-library fixtures only; no user data, devices, models or remote APIs."""
import base64
import json
import sqlite3
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from paa_core.repository import Repository, DomainError
from paa_core.meeting_library import MeetingLibrary, search, document_lines
from paa_core.transcript_store import TranscriptStore
from paa_core.summary_store import SummaryStore
from paa_core.protocol import CoreService, handle, MAX_LINE_BYTES


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='paa-library-')
        self.repo = Repository(Path(self.temp.name))
        self.library = MeetingLibrary(self.repo)
    def tearDown(self):
        self.library.shutdown()
        if self.library.thread:
            self.library.thread.join(3)
            self.assertFalse(self.library.thread.is_alive())
        self.temp.cleanup()
    def seed(self, title='项目周会', count=0, stamp='2026-09-12T02:00:00+00:00'):
        mid = str(uuid.uuid4())
        self.repo.create(mid, str(uuid.uuid4()))
        self.repo.update(mid, status='completed', startedAt=stamp)
        self.repo.rename(mid, title)
        with self.repo.connect() as db:
            db.execute('INSERT INTO transcription_jobs (meetingId,state,modelId,revision,config) VALUES (?,?,?,?,?)', (mid, 'completed', 'small', 'test', '{}'))
            chunk = str(uuid.uuid4())
            db.execute('INSERT INTO audio_chunks VALUES (?,?,?,?,?,?,?)', (chunk, mid, 0, 0, 1, 0, 1))
            for i in range(count):
                db.execute('INSERT INTO transcript_segments VALUES (?,?,?,?,?,?,?,?,?)', (str(uuid.uuid4()), mid, chunk, i, i * 1000, i * 1000 + 500, f'原文片段 {i} 中文 & <script>', None, None))
        return mid
    def summary(self, mid):
        content = {'version': 1, 'title': 'AI标题', 'abstract': '项目延期', 'topics': ['讨论CPU'], 'decisions': [{'text': '决定延期', 'sources': ['secret-ref']}], 'actions': [{'task': '跟进', 'owner': '小王', 'deadline': None, 'status': None, 'sources': ['secret-ref']}], 'risks': ['成本%_'], 'openQuestions': ['何时上线']}
        with self.repo.connect() as db:
            db.execute('INSERT INTO meeting_summaries VALUES (?,?,?,?,?,?,?,?,?,?)', (mid, 'private-task', 'private-hash', '2026-09-12T12:00:00+08:00', 'private-profile', 'service', 'model', '{"private-param":1}', 0, json.dumps(content)))
        return content
    def query(self, text='', **changes):
        return search(self.repo, {'text': text, 'from': None, 'to': None, 'offset': 0, **changes})
    def finish(self, identifier):
        for _ in range(100):
            result = self.library.status(identifier)
            if result['state'] not in ('queued', 'running'):
                return result
            time.sleep(.01)
        self.fail('Background operation did not finish')
    def test_all_history_short_unicode_literal_and_visible_summary_search(self):
        for i in range(55): self.seed(f'普通会议{i}')
        mid = self.seed('📚 汉字 CPU %_ 资料', 61, '2020-01-01T00:00:00+00:00')
        self.summary(mid)
        for word in ['汉', 'cpu', '%_', '原文片段 60', '小王', '何时', 'AI标题']:
            with self.subTest(word=word):
                result = self.query(word)
                self.assertEqual([item['meeting']['id'] for item in result['items']], [mid])
        self.assertEqual(self.query('原文片段 60')['items'][0]['hit']['source'], 'transcript')
        self.assertEqual(self.query('小王')['items'][0]['hit']['locator'], 'actions:0')
        for internal in ['secret-ref', 'private-param', 'private-profile']:
            self.assertEqual(self.query(internal)['items'], [])
        found = []
        for offset in [0, 25, 50]:
            found.extend(item['meeting']['id'] for item in self.query(offset=offset)['items'])
        self.assertEqual(len(set(found)), 56)
        self.assertEqual(found[-1], mid)
    def test_date_offsets_same_instants_and_inclusive_local_days(self):
        before = self.seed('before', stamp='2026-09-11T15:59:59+00:00')
        first = self.seed('first', stamp='2026-09-12T00:00:00+08:00')
        last = self.seed('last', stamp='2026-09-12T23:59:59+08:00')
        after = self.seed('after', stamp='2026-09-13T00:00:00+08:00')
        result = self.query(**{'from': '2026-09-11T16:00:00+00:00', 'to': '2026-09-12T16:00:00+00:00'})
        self.assertEqual([item['meeting']['id'] for item in result['items']], [last, first])
        self.assertNotIn(before, [item['meeting']['id'] for item in result['items']])
        self.assertNotIn(after, [item['meeting']['id'] for item in result['items']])
        with self.assertRaises(DomainError): self.query(**{'from': '2026-09-13T00:00:00Z', 'to': '2026-09-12T00:00:00Z'})
    def test_long_keyword_preview_keeps_complete_match_with_bounded_context(self):
        mid = self.seed(count=1)
        for length in (180, 200):
            with self.subTest(length=length):
                keyword = '汉' * length
                body = '前' * 60 + keyword + '后' * 60
                with self.repo.connect() as db:
                    db.execute('UPDATE transcript_segments SET text=? WHERE meetingId=?', (body, mid))
                hit = self.query(keyword)['items'][0]['hit']
                self.assertEqual(hit['source'], 'transcript')
                self.assertIn(keyword, hit['text'])
                self.assertTrue(hit['text'].startswith('…前'))
                self.assertTrue(hit['text'].endswith('后…'))
                self.assertLessEqual(len(hit['text']), length + 92)
    def test_rename_persists_and_rejects_control_characters_without_changing_sources(self):
        mid = self.seed(count=61)
        self.summary(mid)
        for invalid in ['', '  ', 'a\nb', 'a\x7fb', 'a' * 101, 'a\u2028b']:
            with self.assertRaises(DomainError): self.repo.rename(mid, invalid)
        self.repo.rename(mid, '  新标题📚  ')
        reopened = Repository(self.repo.root)
        self.assertEqual(reopened.get(mid)['title'], '新标题📚')
        with reopened.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM transcript_segments WHERE meetingId=?', (mid,)).fetchone()[0], 61)
            self.assertEqual(json.loads(db.execute('SELECT content FROM meeting_summaries').fetchone()[0])['title'], 'AI标题')
    def test_export_snapshot_is_complete_chunked_and_immutable(self):
        mid = self.seed(count=600)
        self.summary(mid)
        self.repo.update(mid, status='interrupted')
        with self.repo.connect() as db: db.execute("UPDATE transcription_jobs SET state='paused' WHERE meetingId=?", (mid,))
        identifier = self.library.start('export', {'meetingId': mid, 'format': 'txt', 'scope': 'both', 'timestamps': True})['id']
        result = self.finish(identifier)
        self.assertEqual(result['state'], 'completed', result)
        self.repo.rename(mid, 'later-title')
        with self.repo.connect() as db: db.execute("UPDATE transcript_segments SET text='later-text' WHERE meetingId=?", (mid,))
        offset = 0; chunks = []
        while True:
            part = self.library.read(identifier, offset)
            self.assertLess(len(json.dumps(part).encode()), MAX_LINE_BYTES)
            chunks.append(base64.b64decode(part['data'])); offset = part['nextOffset']
            if part['done']: break
        text = b''.join(chunks).decode()
        self.assertIn('原文片段 599', text)
        self.assertIn('00:09:59', text)
        self.assertIn('资料不完整', text)
        self.assertIn('文字记录尚未完成', text)
        self.assertIn('待确认', text)
        self.assertNotIn('later-text', text)
        self.assertNotIn('later-title', text)
        self.assertNotIn('private-', text)
        self.assertNotIn('secret-ref', text)
        self.library.release(identifier)
        with self.assertRaises(DomainError): self.library.read(identifier, 0)
    def test_markdown_escapes_untrusted_text_and_missing_content_fails(self):
        mid = self.seed('a [link](evil) <b>', 1)
        with self.repo.connect() as db:
            text = '\n'.join(document_lines(db, mid, {'format': 'md', 'scope': 'transcript', 'timestamps': False}))
            self.assertIn('\\[link\\]\\(evil\\)', text)
            self.assertIn('\\<script\\>', text)
            self.assertNotIn('[00:00:00', text)
            with self.assertRaises(DomainError): list(document_lines(db, mid, {'format': 'txt', 'scope': 'summary', 'timestamps': False}))
    def test_busy_guards_and_failed_delete_recovery_prevent_late_writes(self):
        mid = self.seed(count=3)
        other = self.seed('keep')
        self.summary(mid)
        for table, state in [('meetings', 'paused'), ('transcription_jobs', 'queued')]:
            field = 'status' if table == 'meetings' else 'state'
            key = 'id' if table == 'meetings' else 'meetingId'
            with self.repo.connect() as db: db.execute(f'UPDATE {table} SET {field}=? WHERE {key}=?', (state, mid))
            with self.assertRaises(DomainError) as error: self.repo.delete(mid)
            self.assertEqual(error.exception.code, 'meeting_busy')
            with self.repo.connect() as db: db.execute(f"UPDATE {table} SET {field}='completed' WHERE {key}=?", (mid,))
        directory = self.repo.path(mid, 'audio.wav').parent; directory.mkdir(parents=True)
        audio = directory / 'audio.wav'; audio.write_bytes(b'controlled')
        (directory / 'recovered.recovering').write_bytes(b'partial recovery')
        original = Path.unlink
        def locked(path, *args, **kwargs):
            if path == audio: raise PermissionError('simulated Windows file lock')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'unlink', locked):
            with self.assertRaises(DomainError): self.repo.delete(mid)
        self.assertTrue(self.repo.get(mid)['deleting'])
        self.assertTrue(self.query()['items'][0]['meeting']['id'])
        store = TranscriptStore(self.repo)
        with self.assertRaises(DomainError): store.start(mid, 'small', 'rev', {})
        self.assertFalse(store.commit({'meetingId': mid, 'nextChunk': 1}, {'startFrame': 1}, []))
        store.state(mid, 'completed')
        summary = SummaryStore(self.repo)
        with self.assertRaises(DomainError): summary.register(mid, {'inputHash': 'new', 'segments': ['x']}, {'profileId': 'x', 'revision': 'r'}, False)
        with self.assertRaises(DomainError): self.repo.rename(mid, 'revive')
        restored = Repository(self.repo.root)
        with self.assertRaises(DomainError): restored.get(mid)
        self.assertEqual(restored.get(other)['title'], 'keep')
        self.assertFalse(directory.exists())
        with restored.connect() as db:
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            for table in ('summary_jobs', 'summary_attempts', 'meeting_summaries', 'transcript_segments', 'audio_chunks', 'transcription_jobs', 'meeting_deletions'):
                self.assertFalse(db.execute(f'SELECT 1 FROM {table} WHERE meetingId=?', (mid,)).fetchone())
    def test_summary_busy_guard_and_late_completion_cannot_recreate_deleted_data(self):
        mid = self.seed(count=1)
        store = SummaryStore(self.repo)
        snapshot = store.snapshot(mid)
        settings = {'profileId': str(uuid.uuid4()), 'revision': 'v1', 'name': 'Test', 'model': 'fake', 'parameters': {}}
        task = store.register(mid, snapshot, settings, False)
        self.assertTrue(store.claim(task))
        with self.assertRaises(DomainError) as error: self.repo.delete(mid)
        self.assertEqual(error.exception.code, 'meeting_busy')
        store.fail(task, 'controlled', 'test failure')
        self.repo.delete(mid)
        store.complete(task, snapshot, settings, {'version': 1})
        self.assertFalse(store.claim(task))
        with self.repo.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM meeting_summaries').fetchone()[0], 0)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_deletion_rejects_symlink_and_preserves_external_file(self):
        mid = self.seed()
        directory = self.repo.path(mid, 'audio.wav').parent
        directory.mkdir(parents=True)
        outside = self.repo.root / 'outside.wav'; outside.write_bytes(b'keep')
        link = directory / 'audio.wav'
        try: link.symlink_to(outside)
        except OSError:
            self.skipTest('Symlink permission is unavailable on this host')
        with self.assertRaises(DomainError): self.repo.delete(mid)
        self.assertEqual(outside.read_bytes(), b'keep')
        self.assertTrue(self.repo.get(mid)['deleting'])
        link.unlink()
        self.repo.delete(mid)
        self.assertEqual(outside.read_bytes(), b'keep')

    def test_schema4_migration_backup_and_failed_ddl_rolls_back(self):
        mid = self.seed()
        with self.repo.connect() as db:
            db.execute('DROP TABLE meeting_deletions'); db.execute('PRAGMA user_version=4')
        original = Repository.connect
        from contextlib import contextmanager
        @contextmanager
        def failing(repo):
            with original(repo) as db:
                db.set_authorizer(lambda action, *_: sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_TABLE else sqlite3.SQLITE_OK)
                yield db
        with patch.object(Repository, 'connect', failing), self.assertRaises(sqlite3.DatabaseError): Repository(self.repo.root)
        with self.repo.connect() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 4)
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE name='meeting_deletions'").fetchall(), [])
        upgraded = Repository(self.repo.root)
        self.assertEqual(upgraded.get(mid)['title'], '项目周会')
        self.assertTrue((self.repo.root / 'meetings.schema4.backup.sqlite3').exists())
    def test_export_cancel_failure_and_expiry_close_private_resources(self):
        mid = self.seed(count=60)
        options = {'meetingId': mid, 'format': 'txt', 'scope': 'transcript', 'timestamps': False}
        with self.assertRaises(DomainError): self.library.export(options, lambda: True)
        # Real output handle is retired on expiry, and no pathname is published.
        identifier = self.library.start('export', options)['id']
        result = self.finish(identifier)
        self.assertEqual(result['state'], 'completed')
        output = self.library.operations[identifier]['file']
        self.library.operations[identifier]['created'] -= 601
        self.library.expire()
        self.assertTrue(output.closed)
        with self.assertRaises(DomainError): self.library.status(identifier)

    def test_worker_does_not_block_control_loop_and_cancel_cleans_snapshot(self):
        entered, release = threading.Event(), threading.Event()
        def held(*_): entered.set(); release.wait(2); return {'items': [], 'hasMore': False}
        with patch('paa_core.meeting_library.search', held):
            identifier = self.library.start('search', {'text': '', 'from': None, 'to': None, 'offset': 0})['id']
            self.assertTrue(entered.wait(1))
            service = CoreService(None); service.repository = self.repo; service.library = self.library
            self.assertEqual(handle({'id': 'h', 'method': 'health'}, service)[0]['result']['storageError'], None)
            from types import SimpleNamespace
            service.recorder = SimpleNamespace(status=lambda: {'state': 'recording'})
            self.assertEqual(handle({'id': 'stop', 'method': 'shutdown'}, service)[0]['error']['code'], 'recording_active')
            self.assertFalse(self.library.stopped)
            self.library.release(identifier); release.set()
        for value in [{'text': '%' * 201, 'from': None, 'to': None, 'offset': 0}, {'text': 'x', 'offset': -1}]:
            with self.assertRaises(DomainError): self.library.start('search', value)

if __name__ == '__main__': unittest.main()
