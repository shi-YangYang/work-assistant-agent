"""Speaker annotations preserve source text, meeting boundaries, and cancellation."""
import multiprocessing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'apps/desktop/core/src'))
from paa_core.audio_store import AudioWriter
from paa_core.repository import Repository, DomainError
from paa_core.transcript_store import TranscriptStore
from paa_core.speaker_store import SpeakerStore, assign_speaker, normalize_speaker_name, SPEAKER_NAME_WHITESPACE
from paa_core.speakers import Speakers
from paa_core.speaker_worker import run_worker, bundled_model_path, verified
from paa_core.meeting_library import document_lines


def held_worker(connection, parent, params):
    connection.send({'progress': str(os.getpid())})
    time.sleep(15)


class SpeakerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = Repository(self.root)
        self.transcripts = TranscriptStore(self.repo)
        self.store = SpeakerStore(self.repo)

    def test_bundled_weights_are_complete_and_path_is_independent_of_cwd(self):
        expected = Path(__file__).resolve().parents[2] / 'packages/voiceprint-engine/resources/models/speaker-community-1'
        self.assertEqual(bundled_model_path(), expected)
        self.assertTrue(verified(bundled_model_path()))
        from paa_voiceprints import model_file
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(model_file(), expected / 'embedding/pytorch_model.bin')
        with patch.dict(os.environ, {'PAA_VOICEPRINT_MODEL': str(expected / 'embedding/pytorch_model.bin')}):
            self.assertEqual(model_file(), expected / 'embedding/pytorch_model.bin')
        with patch('paa_core.speaker_worker.sys.frozen', True, create=True), patch('paa_core.speaker_worker.sys._MEIPASS', str(self.root), create=True):
            self.assertEqual(bundled_model_path(), self.root/'models'/'speaker-community-1')
        self.assertFalse(verified(self.root))

    def meeting(self):
        mid = str(uuid.uuid4())
        self.repo.create(mid, str(uuid.uuid4()))
        path = self.repo.path(mid, 'audio.wav'); path.parent.mkdir(parents=True)
        writer = AudioWriter(path, 16000); writer.write(b'\0\0' * 64000); writer.close()
        self.repo.update(mid, status='completed', sampleRate=16000, frames=64000, durationMs=4000, bytes=128000, audioPath=f'meetings/{mid}/audio.wav')
        job = self.transcripts.start(mid, 'small', 'revision', {})
        self.transcripts.commit(job, dict(startFrame=0,endFrame=64000,contextStart=0,contextEnd=64000), [dict(startMs=0,endMs=1000,text='先讨论需求。'),dict(startMs=1100,endMs=2000,text='我来跟进。'),dict(startMs=2100,endMs=3500,text='多人一起讨论。')], 64000)
        return mid

    def finish(self, mid):
        _, generation = self.store.start(mid)
        self.store.finish(mid, generation, [(0,1050,'a'),(1100,2050,'b'),(2100,2700,'a'),(2700,3500,'b')], 'cpu')
        return self.store.status(mid)

    def test_labels_names_overrides_persist_without_modifying_text_or_ids(self):
        mid = self.meeting(); original = self.transcripts.page(mid)
        status = self.finish(mid)
        page = self.transcripts.page(mid)
        self.assertEqual([s['speaker'] for s in page['segments']], ['speaker_00','speaker_01',None])
        self.assertEqual([(s['id'],s['text']) for s in original['segments']], [(s['id'],s['text']) for s in page['segments']])
        self.store.edit(mid,status['generation'],1,speaker_id='speaker_00',name='张三')
        with self.assertRaises(DomainError): self.store.edit(mid,status['generation'],1,speaker_id='speaker_00',name='过期操作')
        self.store.edit(mid,status['generation'],2,speaker_id='speaker_00',segment_id=page['segments'][1]['id'])
        restarted = Repository(self.root)
        self.assertEqual(SpeakerStore(restarted).status(mid)['speakers'][0]['name'], '张三')
        with restarted.connect() as db:
            exported = '\n'.join(document_lines(db,mid,{'scope':'transcript','format':'txt','timestamps':True}))
        self.assertIn('张三：我来跟进。', exported)
        self.assertEqual(self.transcripts.page(mid)['segments'][1]['speakerName'],'张三')

    def test_names_use_unicode_code_points_and_existing_long_names_remain_readable(self):
        mid = self.meeting()
        status = self.finish(mid)
        safe_whitespace = ' \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000'
        names = ['中' * 40, '中' * 41, 'a' * 100, '😀' * 100, '  张三😀  ', '\ufeff', '\ufeff' + '中' * 99, '\u00a0张\u3000三\u00a0']
        names.extend(char + '😀' * 100 + char for char in safe_whitespace)
        for name in names:
            with self.subTest(name=name):
                status = self.store.edit(mid, status['generation'], status['revision'], speaker_id='speaker_00', name=name)
                self.assertEqual(status['speakers'][0]['name'], name.strip())
                self.assertEqual(self.transcripts.page(mid)['segments'][0]['speakerName'], name.strip())
        invalid = ['a' * 101, '😀' * 101, '\ufeff' + '中' * 100, '张\n三', '张\u0085三', '张\u2028三', *SPEAKER_NAME_WHITESPACE]
        invalid.extend(char + '😀' * 100 + char for char in '\t\n\v\f\r\u001c\u001d\u001e\u001f\u0085\u2028\u2029')
        for name in invalid:
            with self.subTest(name=name), self.assertRaises(DomainError) as error:
                self.store.edit(mid, status['generation'], status['revision'], speaker_id='speaker_00', name=name)
            self.assertEqual(error.exception.code, 'invalid_name')

    def test_name_normalization_matches_the_complete_legacy_python_whitespace_set(self):
        whitespace = {chr(code) for code in range(0x110000) if not chr(code).strip()}
        self.assertEqual(set(SPEAKER_NAME_WHITESPACE), whitespace)
        for char in whitespace:
            with self.subTest(code=f'U+{ord(char):04X}'):
                self.assertEqual(normalize_speaker_name(char + '😀' * 100 + char), '😀' * 100)
                self.assertEqual(normalize_speaker_name(char), '')
        self.assertEqual(normalize_speaker_name(' \ufeff张三\ufeff '), '\ufeff张三\ufeff')
        self.assertEqual(normalize_speaker_name('\ufeff'), '\ufeff')

    def test_cross_meeting_edits_and_busy_delete_are_rejected(self):
        first, second = self.meeting(), self.meeting()
        status = self.finish(first)
        foreign = self.transcripts.page(second)['segments'][0]['id']
        with self.assertRaises(DomainError): self.store.edit(first,status['generation'],status['revision'],speaker_id='speaker_00',segment_id=foreign)
        self.store.start(second)
        with self.assertRaises(DomainError): self.repo.delete(second)
        self.store.stop(second)
        self.assertTrue(self.repo.delete(second)['deleted'])
        self.assertTrue(self.repo.delete(first)['deleted'])

    def test_overlap_and_weak_coverage_remain_unassigned(self):
        self.assertIsNone(assign_speaker(0,1000,[(0,1000,'a'),(100,900,'b')]))
        self.assertIsNone(assign_speaker(0,1000,[(0,100,'a')]))
        self.assertEqual(assign_speaker(0,1000,[(50,950,'a')]),'a')

    def test_retranscription_invalidates_annotations_and_rejects_late_result(self):
        mid = self.meeting(); self.finish(mid)
        job = self.transcripts.rerun(mid,'small','revision',{})
        # Failed/cancelled candidates leave annotations intact.
        self.transcripts.cancel_rerun(mid)
        self.assertEqual(self.store.status(mid)['state'],'completed')
        job = self.transcripts.rerun(mid,'small','revision',{})
        self.transcripts.commit(job,dict(startFrame=0,endFrame=64000,contextStart=0,contextEnd=64000),[dict(startMs=0,endMs=1000,text='新文字')],64000)
        self.assertEqual(self.store.status(mid)['state'],'not_started')
        self.assertFalse(self.store.finish(mid,'legacy',[(0,1000,'a')],'cpu'))
        self.assertIsNone(self.transcripts.page(mid)['segments'][0]['speaker'])

    def test_restart_pauses_inflight_and_schema6_migration_preserves_audio(self):
        mid = self.meeting(); self.store.start(mid)
        self.assertEqual(SpeakerStore(self.repo).status(mid)['state'],'paused')
        with self.repo.connect() as db:
            for table in ('speaker_annotations','meeting_speakers','speaker_jobs'): db.execute(f'DROP TABLE {table}')
            db.execute('PRAGMA user_version=6')
        upgraded = Repository(self.root)
        self.assertTrue(upgraded.get(mid)['audioAvailable'])
        self.assertTrue((self.root/'meetings.schema6.backup.sqlite3').is_file())
        with upgraded.connect() as db: self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],9)

    def test_cancellation_reaps_child_and_does_not_publish(self):
        cancelled = threading.Event(); seen = []
        def progress(pid):
            seen.append(int(pid)); cancelled.set()
        with self.assertRaises(DomainError) as error:
            run_worker({},cancelled,progress,10,target=held_worker)
        self.assertEqual(error.exception.code,'speaker_cancelled')
        self.assertTrue(seen)
        self.assertFalse(any(child.pid == seen[0] for child in multiprocessing.active_children()))

    def test_service_failure_and_cancel_keep_original_transcript(self):
        mid = self.meeting(); before = self.transcripts.page(mid)
        transcription = Mock(); transcription.activity.return_value={'active':False}; transcription.model.status.return_value={'device':'gpu'}
        def failed(*args): raise RuntimeError('private details')
        with patch('paa_core.speakers.verified',return_value=True):
            service=Speakers(self.repo,transcription,runner=failed)
            service.start(mid); service.thread.join(3)
            self.assertEqual(service.status(mid)['state'],'failed')
            self.assertNotIn('private',service.status(mid)['error'])
            self.assertEqual(self.transcripts.page(mid),before)
            service.shutdown()


if __name__ == '__main__': unittest.main()
