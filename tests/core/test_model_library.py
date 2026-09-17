"""Small transactional fixtures for model defaults and candidate publication, never user data."""
import sqlite3
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from functools import partial
import multiprocessing

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'apps/desktop/core/src'))
from paa_core.asr_worker import config_for_mode, DEFAULT_CONFIG, ASRWorker
from paa_core.model_catalog import CATALOG
from paa_core.model_manager import ModelManager, MODEL_ID, REVISION
from paa_core.repository import Repository, DomainError
from paa_core.recorder import Recorder
from paa_core.transcription import Transcription
from paa_core.transcript_store import TranscriptStore
from paa_core.summary_store import SummaryStore
from paa_core.meeting_library import document_lines, search
from paa_core.audio_store import AudioWriter
from test_recording import FakeInput, wait_for
from test_transcription import InlineWorker, HeldProvider
from test_summary import settings as summary_config, content


class ModelLibraryTests(unittest.TestCase):
    def setUp(self):
        device = patch('paa_core.model_manager.hardware', return_value={'cpuName': 'Fixture CPU', 'gpuNames': [], 'gpuName': None, 'gpuAvailable': False, 'gpuBackend': None, 'gpuReason': 'Unavailable'})
        device.start(); self.addCleanup(device.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = Repository(self.root)
        self.store = TranscriptStore(self.repo)
        self.manager = ModelManager(self.root, InlineWorker())
        self.manager.references = self.store.references
        self.recorder = Recorder(self.repo, FakeInput())
        self.service = None

    def tearDown(self):
        if self.service: self.service.shutdown()
        self.manager.shutdown()
        self.recorder.shutdown()
        self.temp.cleanup()

    def audio(self):
        mid = str(uuid.uuid4()); self.repo.create(mid, str(uuid.uuid4()))
        path = self.repo.path(mid, 'audio.wav'); path.parent.mkdir(parents=True)
        writer = AudioWriter(path, 16000); writer.write(b'\x10\x10' * 48000); writer.close()
        self.repo.update(mid, status='completed', sampleRate=16000, frames=48000, durationMs=3000, bytes=96000, audioPath=f'meetings/{mid}/audio.wav')
        return mid

    def publish(self, mid, text='旧内容'):
        job = self.store.start(mid, MODEL_ID, REVISION, DEFAULT_CONFIG)
        self.store.commit(job, self.chunk(), [{'startMs': 100, 'endMs': 500, 'text': text}], 48000)
        return self.store.page(mid)

    @staticmethod
    def chunk():
        return {'startFrame': 0, 'endFrame': 48000, 'contextStart': 0, 'contextEnd': 48000}

    def summary(self, mid):
        store = SummaryStore(self.repo)
        snapshot = store.snapshot(mid); settings = summary_config()
        task = store.register(mid, snapshot, settings, False); store.claim(task)
        store.complete(task, snapshot, settings, content(snapshot['segments']))
        return store, store.get(mid)['result']

    def candidate(self, mid):
        entry = CATALOG['base']
        return self.store.rerun(mid, entry['modelId'], entry['revision'], config_for_mode('mixed'))

    def test_catalog_is_bounded_pinned_and_preserves_legacy_small(self):
        self.assertEqual(list(CATALOG), ['tiny','base','small','medium','large-v3-turbo','large-v3'])
        self.assertEqual(REVISION, '536b0662742c02347bc0e980a01041f333bce120')
        for id, model in CATALOG.items():
            self.assertEqual(len(model['revision']), 40)
            for name, (size, digest) in model['files'].items():
                self.assertNotIn('/', name); self.assertGreater(size, 0); self.assertEqual(len(digest), 64)
            if id.startswith('large'): self.assertIn('preprocessor_config.json', model['files'])
        for invalid in ('../large', '/tmp/model', '', None):
            with self.assertRaises(DomainError): self.manager.entry(invalid)
        self.assertEqual(self.manager.path, self.root / 'models' / ('whisper-small-' + REVISION))

    def test_real_modes_and_persistent_defaults_do_not_change_existing_job(self):
        self.assertEqual(config_for_mode('zh')['initialPrompt'], '简体中文')
        self.assertIsNone(config_for_mode('en')['initialPrompt'])
        self.assertTrue(config_for_mode('mixed')['multilingual'])
        self.assertIsNone(config_for_mode('mixed')['language'])
        for id in ('small','tiny'): self.manager.states[id]['state'] = 'ready'
        self.service = Transcription(self.repo, self.recorder, worker=InlineWorker(), model=self.manager)
        mid = self.audio(); self.service.start(mid)
        wait_for(lambda: self.service.status(mid)['state'] == 'completed')
        self.manager.configure('tiny', 'en')
        self.assertEqual(self.service.status(mid)['published']['language'], 'zh')
        self.assertEqual(self.service.store.job(mid)['modelId'], MODEL_ID)
        restarted = ModelManager(self.root, InlineWorker())
        self.assertEqual(restarted.default_id, 'tiny'); self.assertEqual(restarted.language, 'en'); restarted.shutdown()
        next_id = self.audio(); self.service.start(next_id)
        wait_for(lambda: self.service.status(next_id)['state'] == 'completed')
        self.assertEqual(self.service.status(next_id)['published']['language'], 'en')

    def test_candidate_failure_cancel_and_late_result_preserve_published_version(self):
        mid = self.audio(); before = self.publish(mid); summary, original = self.summary(mid)
        candidate = self.candidate(mid)
        self.assertTrue(candidate['candidate']); self.assertEqual(self.store.page(mid), before)
        self.store.state(mid, 'failed', '测试错误', job=candidate)
        self.assertEqual(self.store.page(mid), before); self.assertEqual(summary.get(mid)['result'], original)
        self.assertTrue(self.store.references(candidate['modelId'], candidate['revision']))
        self.store.cancel_rerun(mid)
        self.assertFalse(self.store.commit(candidate, self.chunk(), [{'startMs': 0, 'endMs': 1, 'text': '迟到'}], 48000))
        self.assertEqual(self.store.page(mid), before); self.assertEqual(summary.get(mid)['result'], original)
        self.assertFalse(self.store.references(candidate['modelId'], candidate['revision']))

    def test_success_atomically_replaces_search_ids_and_marks_summary_stale_without_auto_generation(self):
        mid = self.audio(); before = self.publish(mid, '旧关键词'); summary, original = self.summary(mid)
        calls = []; self.store.on_completed = calls.append
        job = self.candidate(mid)
        self.store.commit(job, self.chunk(), [{'startMs': 0, 'endMs': 500, 'text': '新关键词'}], 48000)
        after = self.store.page(mid)
        self.assertNotEqual(before['segments'][0]['id'], after['segments'][0]['id'])
        self.assertNotEqual(before['publication'], after['publication']); self.assertEqual(calls, [])
        self.assertEqual(self.store.job(mid)['config']['mode'], 'mixed'); self.assertFalse(self.store.job(mid)['candidate'])
        self.assertEqual(summary.get(mid)['result']['content'], original['content']); self.assertTrue(summary.get(mid)['result']['stale'])
        for keyword, count in [('新关键词',1),('旧关键词',0)]:
            self.assertEqual(len(search(self.repo, {'text':keyword,'from':None,'to':None,'offset':0})['items']), count)
        with self.assertRaises(DomainError) as error: self.store.page(mid, before['nextCursor'], before['publication'])
        self.assertEqual(error.exception.code, 'transcript_changed')
        with self.repo.connect() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM transcript_segments WHERE id=?', (before['segments'][0]['id'],)).fetchone())
            exported = '\n'.join(document_lines(db, mid, {'scope':'both','format':'txt','timestamps':True}))
        self.assertIn('纪要待更新', exported); self.assertIn('新关键词', exported)
        snapshot = summary.snapshot(mid); settings = summary_config(); task = summary.register(mid,snapshot,settings,False)
        summary.claim(task); summary.complete(task,snapshot,settings,content(snapshot['segments']))
        self.assertFalse(summary.get(mid)['result']['stale'])

    def test_failed_publication_rolls_back_candidate_and_original_together(self):
        mid = self.audio(); before = self.publish(mid); job = self.candidate(mid)
        with self.repo.connect() as db: db.execute("CREATE TRIGGER reject_publication BEFORE INSERT ON transcript_publications BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.store.commit(job,self.chunk(),[{'startMs':0,'endMs':1,'text':'替换'}],48000)
        self.assertEqual(self.store.page(mid),before); self.assertEqual(self.store.job(mid)['processedFrames'],0)
        with self.repo.connect() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM candidate_segments').fetchone()[0],0)

    def test_summary_and_candidate_registration_are_reciprocally_exclusive(self):
        mid=self.audio(); self.publish(mid); summary=SummaryStore(self.repo); old=summary.snapshot(mid)
        job=self.candidate(mid)
        with self.assertRaises(DomainError): summary.register(mid,old,summary_config(),False)
        self.store.cancel_rerun(mid)
        task=summary.register(mid,old,summary_config(),False)
        with self.assertRaises(DomainError): self.candidate(mid)
        summary.fail(task,'test','test'); self.candidate(mid)
        with self.assertRaises(DomainError): summary.snapshot(mid)

    def test_stale_summary_snapshot_cannot_register_after_publication(self):
        mid=self.audio(); self.publish(mid); summary=SummaryStore(self.repo); snapshot=summary.snapshot(mid)
        job=self.candidate(mid); self.store.commit(job,self.chunk(),[{'startMs':0,'endMs':1,'text':'new'}],48000)
        with self.assertRaises(DomainError): summary.register(mid,snapshot,summary_config(),False)

    def test_candidate_restart_and_missing_model_keep_original_snapshot(self):
        mid=self.audio(); before=self.publish(mid); candidate=self.candidate(mid)
        recovered=TranscriptStore(Repository(self.root))
        self.assertEqual(recovered.job(mid)['state'],'paused'); self.assertEqual(recovered.job(mid)['generation'],candidate['generation'])
        self.assertEqual(recovered.page(mid),before)
        self.service=Transcription(self.repo,self.recorder,worker=InlineWorker(),model=self.manager)
        with self.assertRaises(DomainError): self.service.start(mid)
        self.assertEqual(self.service.store.job(mid)['modelId'],candidate['modelId'])

    def test_resume_reports_original_model_blocker_even_when_default_is_ready(self):
        entry = CATALOG['tiny']
        self.manager.states['small']['state'] = 'ready'
        self.service = Transcription(self.repo, self.recorder, worker=InlineWorker(), model=self.manager)
        for model_state, revision, expected_code in (
            ('missing', entry['revision'], 'model_not_ready'),
            ('error', entry['revision'], 'model_not_ready'),
            ('ready', '0' * 40, 'model_mismatch'),
        ):
            with self.subTest(model_state=model_state, revision=revision):
                mid = self.audio()
                with self.service.control_lock:
                    job = self.service.store.start(mid, entry['modelId'], revision, config_for_mode('en'))
                    self.service.store.state(mid, 'paused', job=job)
                self.manager.states['tiny']['state'] = model_state
                before = self.service.store.job(mid)
                status = self.service.status(mid)
                self.assertEqual(self.manager.status()['state'], 'ready')
                self.assertFalse(status['canContinue'])
                self.assertIsNone(status['error'])
                self.assertIn('Whisper tiny', status['continuationBlockedReason'])
                if expected_code == 'model_mismatch':
                    self.assertIn(revision, status['continuationBlockedReason'])
                self.assertEqual(status['actual']['modelId'], entry['modelId'])
                self.assertEqual(status['actual']['revision'], revision)
                self.assertEqual(status['actual']['language'], 'en')
                with self.assertRaises(DomainError) as error: self.service.start(mid)
                self.assertEqual(error.exception.code, expected_code)
                self.assertEqual(self.service.store.job(mid), before)
                self.assertEqual(self.manager.default_id, 'small')
                if expected_code == 'model_not_ready':
                    self.manager.states['tiny']['state'] = 'ready'
                    restored = self.service.status(mid)
                    self.assertTrue(restored['canContinue'])
                    self.assertIsNone(restored['continuationBlockedReason'])
                    self.assertEqual(self.service.store.job(mid), before)

    def test_default_and_unfinished_references_block_removal_and_occupied_files_report_errors(self):
        with self.assertRaises(DomainError): self.manager.remove('small')
        mid=self.audio();self.publish(mid);candidate=self.candidate(mid)
        with self.assertRaises(DomainError): self.manager.remove('base')
        self.store.cancel_rerun(mid)
        path=self.manager.path_for('base');path.mkdir(parents=True);(path/'model.bin').write_bytes(b'fixture')
        with patch('paa_core.model_manager.shutil.rmtree',side_effect=PermissionError('held')),self.assertRaises(DomainError) as error: self.manager.remove('base')
        self.assertEqual(error.exception.code,'model_remove_failed');self.assertTrue(path.exists())
        self.manager.remove('base');self.assertFalse(path.exists())

    def test_model_validation_waits_for_inference_and_cancel_does_not_interrupt_it(self):
        from paa_core.asr_worker import InferenceToken
        ctx = multiprocessing.get_context('spawn')
        entered, release = ctx.Semaphore(0), ctx.Semaphore(0)
        worker = ASRWorker(partial(HeldProvider, entered=entered, release=release))
        result, errors = [], []
        token = InferenceToken()
        def infer():
            try: result.extend(worker.infer('active', b'\0\0' * 16000, 16000, DEFAULT_CONFIG))
            except Exception as exc: errors.append(exc)
        def validate():
            try: worker.validate('candidate', DEFAULT_CONFIG, token)
            except Exception as exc: errors.append(exc)
        inference = threading.Thread(target=infer); validation = threading.Thread(target=validate)
        try:
            inference.start(); self.assertTrue(entered.acquire(timeout=5))
            validation.start(); token.cancel()
            self.assertTrue(inference.is_alive()); self.assertEqual(result, [])
            release.release(); inference.join(5); validation.join(5)
            self.assertFalse(inference.is_alive()); self.assertFalse(validation.is_alive())
            self.assertEqual(result[0]['text'], '测试文字')
            self.assertEqual(len(errors), 1); self.assertEqual(errors[0].code, 'transcription_paused')
            self.assertEqual(worker.loaded[0], 'active')
        finally:
            release.release(); token.cancel(); inference.join(5)
            if validation.ident: validation.join(5)
            worker.shutdown()

    def test_download_disk_precheck_and_single_preparer_never_use_network(self):
        from collections import namedtuple
        usage = namedtuple('Usage', 'total used free')(100,100,0)
        with patch('paa_core.model_manager.shutil.disk_usage', return_value=usage), patch('paa_core.model_manager.urllib.request.build_opener') as opener:
            self.manager.download('tiny')
            wait_for(lambda: self.manager.status()['models'][0]['state'] == 'error')
            opener.assert_not_called()
            self.assertIn('磁盘空间不足', self.manager.status()['models'][0]['error'])
        self.manager.thread = object()
        try:
            with self.assertRaises(DomainError) as error: self.manager.download('base')
            self.assertEqual(error.exception.code, 'model_busy')
        finally: self.manager.thread = None

    def test_cancelled_candidate_and_deleted_meeting_reject_late_publication(self):
        mid=self.audio();self.publish(mid);job=self.candidate(mid)
        with self.assertRaises(DomainError):self.repo.delete(mid)
        self.store.state(mid,'failed','test',job=job)
        self.repo.delete(mid)
        self.assertFalse(self.store.commit(job,self.chunk(),[{'startMs':0,'endMs':1,'text':'late'}],48000))
        with self.repo.connect() as db:
            for table in ('candidate_segments','candidate_chunks','candidate_jobs','transcript_publications','meetings'):
                self.assertIsNone(db.execute(f'SELECT 1 FROM {table} WHERE '+('id' if table == 'meetings' else 'meetingId')+'=?',(mid,)).fetchone())

    def test_schema5_migration_backs_up_and_preserves_published_audio_and_segments(self):
        mid=self.audio();before=self.publish(mid)
        with self.repo.connect() as db:
            for table in ('candidate_segments','candidate_chunks','candidate_jobs','transcript_publications'):db.execute('DROP TABLE '+table)
            db.execute('PRAGMA user_version=5')
        upgraded=Repository(self.root)
        self.assertTrue((self.root/'meetings.schema5.backup.sqlite3').exists())
        self.assertTrue(upgraded.get(mid)['audioAvailable']);self.assertEqual(TranscriptStore(upgraded).page(mid),before)
        with upgraded.connect() as db:self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],9)
