"""Shared speaker templates, live publication and logout fences without model calls."""
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import uuid
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'apps/desktop/core/src'))
from paa_core.repository import Repository, DomainError
from paa_core.audio_store import AudioWriter
from paa_core.transcript_store import TranscriptStore
from paa_core.speaker_store import SpeakerStore
from paa_core.voiceprints import Voiceprints
from paa_core.protocol import serve
from paa_voiceprints import MODEL_ID, DIMENSION, VoiceprintError, isolated_turns, match, validate_profiles


def vector(index=0):
    return [float(i==index) for i in range(DIMENSION)]


def profiles():
    return [{'memberId':'alice','name':'张三','templates':[vector()]}]


class VoiceprintTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.repo=Repository(Path(temporary.name));self.transcripts=TranscriptStore(self.repo)
        self.store=SpeakerStore(self.repo)

    def service(self, runner=None):
        recorder=Mock();recorder.lock=threading.RLock();recorder.session=None
        recorder.status.return_value={'meetingId':None,'state':'idle'}
        transcription=Mock();transcription.store=self.transcripts
        transcription.model.status.return_value={'device':'cpu'}
        transcription.activity.return_value={'active':False}
        speakers=Mock();speakers.store=self.store;speakers.active.return_value=False
        speakers.path=Path('unused-test-model')
        value=Voiceprints(self.repo,recorder,transcription,speakers,runner=runner)
        value.shutdown()  # Tests drive a single bounded scheduling iteration explicitly.
        value.cancelled=threading.Event()
        value.configure('company/account',MODEL_ID,profiles())
        return value

    def meeting(self):
        mid=str(uuid.uuid4());self.repo.create(mid,str(uuid.uuid4()))
        path=self.repo.path(mid,'audio.wav');path.parent.mkdir(parents=True)
        writer=AudioWriter(path,16000);writer.write(b'\0\0'*320000);writer.close()
        self.repo.update(mid,status='completed',sampleRate=16000,frames=320000,durationMs=20000,bytes=640000,audioPath=f'meetings/{mid}/audio.wav')
        job=self.transcripts.start(mid,'small','revision',{})
        self.transcripts.commit(job,dict(startFrame=0,endFrame=240000,contextStart=0,contextEnd=240000),[dict(startMs=0,endMs=6000,text='第一句话。'),dict(startMs=7000,endMs=14000,text='第二句话。')],None)
        return mid

    def test_rejects_incompatible_or_untrusted_templates_atomically(self):
        service=self.service()
        with self.assertRaises(DomainError):service.configure('other','wrong',profiles())
        self.assertEqual(service.scope,'company/account')
        for invalid in ([[0.]*DIMENSION],[[float('nan')]*DIMENSION],[[True]*DIMENSION],[[1.]*(DIMENSION-1)]):
            with self.subTest(invalid=type(invalid[0][0]).__name__):
                with self.assertRaises(VoiceprintError):validate_profiles(MODEL_ID,[{**profiles()[0],'templates':invalid}])
        with self.assertRaises(VoiceprintError):validate_profiles(MODEL_ID,profiles()*2)

    def test_short_unknown_and_ambiguous_speech_is_not_named(self):
        self.assertEqual(match([vector()],profiles(),6)['memberId'],'alice')
        self.assertIsNone(match([vector()],profiles(),2.9))
        self.assertIsNone(match([vector(1)],profiles(),6))
        self.assertIsNone(match([vector()],profiles()+[{'memberId':'bob','name':'李四','templates':[vector()]}],6))
        self.assertIsNone(match([vector(),vector(),vector(1)],profiles(),12))
        self.assertEqual(isolated_turns([(0,10,'a'),(4,6,'b')]),{'a':[(0,4),(6,10)]})

    def test_live_labels_become_names_and_manual_edits_survive_final_publication(self):
        mid=self.meeting();generation=self.store.begin_live(mid,'company/account')
        turns=[(0,6000,'a'),(7000,14000,'b')]
        self.store.publish(mid,generation,turns,'cpu',end_ms=15000)
        page=self.transcripts.page(mid);ids=[s['id'] for s in page['segments']]
        self.assertEqual(page['segments'][0]['speakerName'],'说话人 A')
        self.store.publish(mid,generation,turns,'cpu',identities={'a':{'memberId':'alice','name':'张三'}},end_ms=15000)
        self.assertEqual(self.transcripts.page(mid)['segments'][0]['speakerName'],'张三')
        state=self.store.status(mid)
        self.store.edit(mid,generation,state['revision'],speaker_id='speaker_00',name='人工姓名')
        state=self.store.status(mid)
        self.store.edit(mid,generation,state['revision'],speaker_id=None,segment_id=ids[1])
        self.store.finish(mid,generation,turns,'cpu',{'a':{'memberId':'alice','name':'自动姓名'}})
        page=self.transcripts.page(mid)
        self.assertEqual([s['id'] for s in page['segments']],ids)
        self.assertEqual(page['segments'][0]['speakerName'],'人工姓名')
        self.assertIsNone(page['segments'][1]['speaker'])

    def test_window_reads_saved_audio_and_does_not_modify_transcript_content(self):
        captured=[]
        def runner(params,cancelled,progress,timeout):
            captured.append(params)
            self.assertTrue(Path(params['audio']).is_file())
            return {'turns':[(0,6000,'a'),(7000,14000,'a')],'device':'cpu','identities':{'a':{'memberId':'alice','name':'张三'}},'embeddings':{'a':{'templates':[vector()],'speechSeconds':13}}}
        service=self.service(runner);mid=self.meeting();before=self.transcripts.page(mid)
        version,scope,people=service.snapshot()
        self.assertTrue(service.process(mid,version,scope,people,service.cancelled))
        after=self.transcripts.page(mid)
        self.assertEqual([(s['id'],s['text']) for s in before['segments']],[(s['id'],s['text']) for s in after['segments']])
        self.assertEqual(after['segments'][0]['speakerName'],'张三')
        self.assertEqual(self.store.status(mid)['processedMs'],15000)
        self.assertFalse(Path(captured[0]['audio']).exists())

    def test_schema7_upgrade_preserves_old_names_assignments_and_backup(self):
        mid=self.meeting();generation=self.store.begin_live(mid,'company/account')
        self.store.finish(mid,generation,[(0,6000,'a')],'cpu')
        status=self.store.status(mid)
        self.store.edit(mid,generation,status['revision'],speaker_id='speaker_00',name='原有姓名')
        with self.repo.connect() as db:
            for table,columns in {'meeting_speakers':['manual','memberId'],'speaker_annotations':['manual'],'speaker_jobs':['processedMs','voiceprintScope']}.items():
                for column in columns:db.execute(f'ALTER TABLE {table} DROP COLUMN {column}')
            db.execute('PRAGMA user_version=7')
        upgraded=Repository(self.repo.root)
        self.assertTrue((self.repo.root/'meetings.schema7.backup.sqlite3').is_file())
        self.assertEqual(TranscriptStore(upgraded).page(mid)['segments'][0]['speakerName'],'原有姓名')
        with upgraded.connect() as db:
            self.assertEqual(db.execute('SELECT manual FROM meeting_speakers WHERE meetingId=?',(mid,)).fetchone()[0],1)
            self.assertEqual(db.execute('SELECT manual FROM speaker_annotations WHERE meetingId=?',(mid,)).fetchone()[0],1)

    def test_pause_keeps_pending_audio_and_cancels_only_inflight_work(self):
        service=self.service();mid=self.meeting()
        service.watch(mid);service.inflight=mid;token=service.cancelled
        service.pause(mid,keep_pending=True)
        self.assertTrue(token.is_set())
        self.assertIn(mid,service.meetings)
        self.assertFalse(service.cancelled.is_set())
        service.pause(mid)
        self.assertNotIn(mid,service.meetings)

    def test_accumulated_identity_does_not_override_manual_or_forget_a_known_name(self):
        mid=self.meeting();generation=self.store.begin_live(mid,'company/account')
        turns=[(0,6000,'a')]
        self.store.publish(mid,generation,turns,'cpu',end_ms=15000,aliases={'a':'speaker_00'})
        self.store.identify(mid,generation,{'speaker_00':{'memberId':'alice','name':'张三'}})
        self.store.publish(mid,generation,turns,'cpu',end_ms=15000,aliases={'a':'speaker_00'})
        self.assertEqual(self.transcripts.page(mid)['segments'][0]['speakerName'],'张三')
        state=self.store.status(mid)
        self.store.edit(mid,generation,state['revision'],speaker_id='speaker_00',name='本人更正')
        self.store.identify(mid,generation,{'speaker_00':{'memberId':'bob','name':'不能覆盖'}})
        self.assertEqual(self.transcripts.page(mid)['segments'][0]['speakerName'],'本人更正')
        self.store.finish(mid,generation,turns,'cpu',{'a':{'memberId':'bob','name':'模型改判也不能覆盖'}})
        self.assertEqual(self.transcripts.page(mid)['segments'][0]['speakerName'],'本人更正')

    def test_tiny_boundary_turn_cannot_steal_another_employees_existing_label(self):
        mid=self.meeting();generation=self.store.begin_live(mid,'company/account')
        self.store.publish(mid,generation,[(0,6000,'a')],'cpu',identities={'a':{'memberId':'alice','name':'张三'}},end_ms=6000)
        self.store.publish(mid,generation,[(1000,1017,'b'),(1017,6000,'a'),(7000,14000,'b')],'cpu',identities={'a':{'memberId':'alice','name':'张三'},'b':{'memberId':'bob','name':'李四'}},end_ms=15000)
        self.assertEqual([s['speakerName'] for s in self.transcripts.page(mid)['segments']],['张三','李四'])

    def test_final_merge_removes_unused_automatic_labels_but_keeps_manual_names(self):
        mid=self.meeting();generation=self.store.begin_live(mid,'company/account')
        self.store.publish(mid,generation,[(0,6000,'a'),(7000,14000,'b')],'cpu',end_ms=15000)
        self.store.finish(mid,generation,[(0,14000,'merged')],'cpu')
        self.assertEqual(len(self.store.status(mid)['speakers']),1)

    def test_clear_and_scope_change_reject_inflight_live_and_final_names(self):
        for scope,people in ((None,[]),('different/company',profiles())):
            with self.subTest(scope=scope):
                service=self.service();mid=self.meeting()
                def runner(*args):
                    service.configure(scope,MODEL_ID,people)
                    return {'turns':[(0,6000,'a')],'device':'cpu','identities':{'a':{'memberId':'alice','name':'泄漏姓名'}}}
                service.runner=runner
                version,oldscope,oldpeople=service.snapshot();token=service.cancelled
                self.assertFalse(service.process(mid,version,oldscope,oldpeople,token))
                self.assertIsNone(self.transcripts.page(mid)['segments'][0]['speakerName'])
                self.assertFalse(service.publish_final(version,mid,'legacy',{'turns':[(0,6000,'a')],'device':'cpu','identities':{'a':{'memberId':'alice','name':'泄漏姓名'}}}))

    def test_mixed_live_cluster_cannot_relabel_previous_or_future_words_as_one_employee(self):
        def runner(*_):
            return {'turns':[(0,14000,'merged')],'device':'cpu','identities':{},
                    'embeddings':{'merged':{'templates':[vector(),vector(1)],'speechSeconds':12}},
                    'ambiguousLabels':['merged']}
        service=self.service(runner);mid=self.meeting()
        generation=self.store.begin_live(mid,'company/account')
        self.store.publish(mid,generation,[(0,6000,'a')],'cpu',identities={'a':{'memberId':'alice','name':'张三'}},end_ms=0)
        with self.repo.connect() as db:db.execute('UPDATE speaker_jobs SET processedMs=0 WHERE meetingId=?',(mid,))
        version,scope,people=service.snapshot()
        service.process(mid,version,scope,people,service.cancelled)
        page=self.transcripts.page(mid)
        self.assertEqual(page['segments'][0]['speakerName'],'张三')
        self.assertIsNone(page['segments'][1]['speakerName'])
        self.assertEqual(len(self.store.status(mid)['speakers']),1)

    def test_large_templates_are_allowed_only_on_configure_not_other_commands(self):
        class Service:
            speakers=voiceprints=library=summary=transcription=recorder=None
            def dispatch(self,method,params):return {'method':method},False
        payload={'id':'x','method':'voiceprints.configure','params':{'padding':'x'*70000}}
        output=io.BytesIO();serve(io.BytesIO((json.dumps(payload)+'\n').encode()),output,Service())
        self.assertEqual(json.loads(output.getvalue())['result']['method'],'voiceprints.configure')
        payload['method']='health';output=io.BytesIO();serve(io.BytesIO((json.dumps(payload)+'\n').encode()),output,Service())
        self.assertEqual(json.loads(output.getvalue())['error']['code'],'invalid_request')


if __name__=='__main__':unittest.main()
