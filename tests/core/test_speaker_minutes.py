"""Speaker-aware minutes contracts using authored text and temporary databases."""
import copy
import json
import sqlite3
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_summary as summary_fixtures
from test_summary import content, seed, settings
from test_recording import wait_for
from paa_core.meeting_summary import IDENTITY_NOTE, MeetingSummary, model_input, validate
from paa_core.meeting_library import document_lines, search
from paa_core.repository import DomainError, Repository
from paa_core.speaker_store import SpeakerStore
from paa_core.voiceprints import Voiceprints


class SpeakerMinutesTests(unittest.TestCase):
    setUp = summary_fixtures.SummaryTests.setUp
    tearDown = summary_fixtures.SummaryTests.tearDown
    finish = summary_fixtures.SummaryTests.finish
    def speakers(self, mid, state='completed'):
        store = SpeakerStore(self.repo)
        with self.repo.connect() as db:
            segments = db.execute('SELECT id FROM transcript_segments WHERE meetingId=? ORDER BY sequence', (mid,)).fetchall()
            db.execute('INSERT INTO speaker_jobs (meetingId,generation,state) VALUES (?,?,?)', (mid, 'legacy', state))
            db.execute('INSERT INTO meeting_speakers (meetingId,id,name,memberId) VALUES (?,?,?,?)', (mid, 'speaker_00', '陈甲', 'private-member'))
            db.execute('INSERT INTO meeting_speakers (meetingId,id,name) VALUES (?,?,?)', (mid, 'speaker_01', '说话人 B'))
            for index, segment in enumerate(segments):
                db.execute('INSERT INTO speaker_annotations (meetingId,segmentId,speakerId) VALUES (?,?,?)', (mid, segment[0], f'speaker_0{index % 2}'))
        return store, [row[0] for row in segments]

    def test_protocol_input_modes_and_export_options_are_validated(self):
        from paa_core.protocol import CoreService, handle
        from paa_core.meeting_library import MeetingLibrary
        mid = seed(self.repo, 2)
        self.service.configure(settings(), False)
        core = CoreService.__new__(CoreService)
        core.summary, core.repository = self.service, self.repo
        response, _ = handle({'id': 'mode', 'method': 'summary.generate', 'params': {'meetingId': mid, 'inputMode': 'text'}}, core)
        self.assertIn('result', response)
        self.assertEqual(self.finish(mid)['result']['inputMode'], 'text')
        for mode in ('invalid', None, {}, True):
            response, _ = handle({'id': 'mode', 'method': 'summary.generate', 'params': {'meetingId': mid, 'inputMode': mode}}, core)
            self.assertEqual(response['error']['code'], 'invalid_params')
        library = MeetingLibrary(self.repo)
        try:
            for speakers in (None, 'false', 0):
                with self.assertRaises(DomainError):
                    library.start('export', {'meetingId': mid, 'format': 'txt', 'scope': 'transcript', 'timestamps': False, 'speakers': speakers})
            operation = library.start('export', {'meetingId': mid, 'format': 'txt', 'scope': 'transcript', 'timestamps': False, 'speakers': False})['id']
            wait_for(lambda: library.status(operation)['state'] == 'completed')
        finally:
            library.shutdown()
            if library.thread:
                library.thread.join(1)

    def test_snapshot_modes_privacy_and_identity_assignment_sources(self):
        mid = seed(self.repo, 3)
        speakers, ids = self.speakers(mid)
        speakers.edit(mid, 'legacy', 0, speaker_id='speaker_01', name='陈乙')
        speakers.edit(mid, 'legacy', 1, speaker_id=None, segment_id=ids[2])
        snapshot = self.service.store.snapshot(mid)
        self.assertEqual(snapshot['segments'][0]['speaker'], {'id': 'speaker_00', 'name': '陈甲', 'identitySource': 'voiceprint', 'assignmentSource': 'automatic'})
        self.assertEqual(snapshot['segments'][1]['speaker']['identitySource'], 'manual')
        self.assertIsNone(snapshot['segments'][2]['speaker'])
        self.assertNotIn('private-member', json.dumps(snapshot))
        self.assertNotIn('memberId', json.dumps(snapshot))
        self.assertTrue(snapshot['speakerIncomplete'])
        plain = self.service.store.snapshot(mid, 'text')
        self.assertTrue(all('speaker' not in segment for segment in plain['segments']))
        self.assertFalse(plain['speakerIncomplete'])
        speakers.edit(mid, 'legacy', 2, speaker_id='speaker_01', segment_id=ids[0])
        self.assertEqual(self.service.store.snapshot(mid)['segments'][0]['speaker']['assignmentSource'], 'manual')

    def test_rename_reassignment_and_running_changes_mark_only_speaker_results_stale(self):
        mid = seed(self.repo, 3)
        speakers, ids = self.speakers(mid)
        self.service.configure(settings(), True)
        self.provider.release.clear()
        self.service.generate(mid)
        self.assertTrue(self.provider.entered.wait(1))
        speakers.edit(mid, 'legacy', 0, speaker_id='speaker_00', name='更正姓名')
        self.assertTrue(self.service.get(mid)['task']['stale'])
        self.provider.release.set()
        self.assertTrue(self.finish(mid)['result']['stale'])
        sent = json.loads(self.provider.calls[0][1][-1]['content'])
        self.assertEqual(sent['segments'][0]['speaker']['name'], '陈甲（声纹匹配，待确认）')
        self.service.generate(mid)
        self.assertFalse(self.finish(mid)['result']['stale'])
        speakers.edit(mid, 'legacy', 1, speaker_id='speaker_01', segment_id=ids[0])
        self.assertTrue(self.service.get(mid)['result']['stale'])
        self.service.generate(mid, input_mode='text')
        self.assertFalse(self.finish(mid)['result']['stale'])
        speakers.edit(mid, 'legacy', 2, speaker_id='speaker_00', name='再次改名')
        speakers.edit(mid, 'legacy', 3, speaker_id='speaker_00', segment_id=ids[0])
        self.assertFalse(self.service.get(mid)['result']['stale'])
        plain = json.loads(self.provider.calls[-1][1][-1]['content'])
        self.assertEqual(plain['inputMode'], 'text')
        self.assertTrue(all('speaker' not in segment for segment in plain['segments']))

    def test_text_publication_change_and_original_citations_survive(self):
        mid = seed(self.repo, 2)
        self.service.configure(settings(), False)
        self.service.generate(mid, input_mode='text')
        self.finish(mid)
        snapshot = self.service.store.snapshot(mid, 'text')
        original = snapshot['segments'][0]
        with self.repo.connect() as db:
            db.execute('UPDATE transcript_segments SET text=? WHERE id=?', ('修改后的文字', original['id']))
            db.execute('INSERT INTO transcript_publications VALUES (?,?,1)', (mid, 'new-publication'))
        self.assertTrue(self.service.get(mid)['result']['stale'])
        self.assertEqual(self.service.store.source(mid, original['id']), original)
        with self.repo.connect() as db:
            exported = '\n'.join(document_lines(db, mid, dict(scope='summary', format='txt', timestamps=False)))
        self.assertIn(original['text'], exported)
        self.assertNotIn('修改后的文字', exported)
        self.assertIn('待更新', exported)

    def test_waits_for_pending_before_job_exists_and_keeps_model_operations_free(self):
        mid = seed(self.repo, 2)
        voiceprints = Voiceprints.__new__(Voiceprints)
        voiceprints.lock, voiceprints.meetings = threading.RLock(), {mid}
        voiceprints.speakers = SimpleNamespace(store=SpeakerStore(self.repo))
        self.service.speaker_pending = voiceprints.pending
        current = settings()
        self.service.configure(current, True)
        self.service.on_completed(mid)
        self.assertEqual(self.service.get(mid)['task']['state'], 'waiting_speakers')
        self.assertEqual(self.provider.calls, [])
        with patch.object(self.provider, 'check', return_value={'ok': True}):
            operation = self.service.operation('check', current)['id']
            wait_for(lambda: self.service.operation_status(operation)['state'] == 'completed')
        speakers, _ = self.speakers(mid)
        with voiceprints.lock:
            voiceprints.meetings.clear()
        self.service.wait_wake.set()
        self.finish(mid)
        payload = json.loads(self.provider.calls[0][1][-1]['content'])
        self.assertEqual(payload['segments'][0]['speaker']['name'], '陈甲（声纹匹配，待确认）')
        speakers.edit(mid, 'legacy', 0, speaker_id='speaker_00', name='新姓名')
        self.service.on_completed(mid)
        self.assertEqual(len(self.provider.calls), 1)
        self.assertTrue(self.service.get(mid)['result']['stale'])

    def test_wait_timeout_failure_disable_and_restart_do_not_repeat_calls(self):
        self.service.configure(settings(), True)
        self.service.speaker_wait_seconds = .05
        mid = seed(self.repo, 2)
        self.service.speaker_pending = lambda _: True
        self.service.on_completed(mid)
        self.assertEqual(self.service.get(mid)['task']['state'], 'waiting_speakers')
        self.assertTrue(self.finish(mid)['result']['speakerIncomplete'])
        self.service.speaker_pending = lambda _: False
        self.service.on_completed(mid)
        self.assertEqual(len(self.provider.calls), 1)
        failed = seed(self.repo, 2)
        speakers, _ = self.speakers(failed, 'running')
        self.service.speaker_pending = self.service.store.speakers_pending
        self.service.on_completed(failed)
        speakers.stop(failed, '测试失败')
        self.service.wait_wake.set()
        self.assertTrue(self.finish(failed)['result']['speakerIncomplete'])
        pending = seed(self.repo, 2)
        self.service.speaker_wait_seconds = 180
        self.service.speaker_pending = lambda _: True
        self.service.on_completed(pending)
        self.service.shutdown()
        self.service = MeetingSummary(self.repo, self.provider)
        self.service.configure(settings(), True)
        self.assertEqual(self.service.get(pending)['task']['state'], 'interrupted')
        self.service.on_completed(pending)
        self.assertEqual(len(self.provider.calls), 2)
        disabled = seed(self.repo, 2)
        self.service.speaker_pending = lambda _: True
        self.service.on_completed(disabled)
        self.service.configure(settings(), False)
        self.assertEqual(self.service.get(disabled)['task']['state'], 'interrupted')
        self.assertEqual(len(self.provider.calls), 2)

    def test_version2_citations_and_speaker_binding_reject_malformed_output(self):
        mid = seed(self.repo, 3)
        _, ids = self.speakers(mid)
        snapshot = self.service.store.snapshot(mid)
        good = content(snapshot['segments'])
        good['speakerSummaries'] = [{'speakerId': 'speaker_00', 'name': '陈甲', 'points': [{'text': '提议评估', 'sources': [ids[0]]}], 'commitments': []}]
        self.assertEqual(validate(json.dumps(good), snapshot)['speakerSummaries'][0]['name'], '陈甲（声纹匹配，待确认）')
        cases = []
        for field in ('topics', 'agreements', 'disagreements', 'risks', 'openQuestions', 'suggestions'):
            bad = copy.deepcopy(good); bad[field] = [{'text': '内容', 'sources': ['invented']}]; cases.append(bad)
        bad = copy.deepcopy(good); bad['overviewSources'] = []; cases.append(bad)
        bad = copy.deepcopy(good); bad['version'] = 1; cases.append(bad)
        bad = copy.deepcopy(good); bad['speakerSummaries'][0]['name'] = '错误姓名'; cases.append(bad)
        bad = copy.deepcopy(good); bad['speakerSummaries'][0]['points'][0]['sources'] = [ids[1]]; cases.append(bad)
        bad = copy.deepcopy(good); bad['speakerSummaries'][0]['speakerId'] = 'absent'; cases.append(bad)
        bad = copy.deepcopy(good); bad['actions'][0]['blocker'] = 1; cases.append(bad)
        for bad in cases:
            with self.assertRaises(DomainError):
                validate(json.dumps(bad), snapshot)
        with self.assertRaises(DomainError):
            validate(json.dumps(good), self.service.store.snapshot(mid, 'text'))

    def test_automatic_identity_is_qualified_everywhere_until_manual_confirmation(self):
        mid = seed(self.repo, 2)
        speakers, ids = self.speakers(mid)
        with self.repo.connect() as db:
            db.execute("UPDATE meeting_speakers SET name='王宁' WHERE meetingId=? AND id='speaker_00'", (mid,))
            db.execute('UPDATE transcript_segments SET text=? WHERE id=?', ('我来汇总内部试用反馈，完成日期未定。', ids[0]))
        snapshot = self.service.store.snapshot(mid)
        raw = content(snapshot['segments'])
        # Reproduce the real response: overview omits Wang's source, action owner is
        # null, but prose and the speaker heading assert the automatic identity.
        raw['abstract'] = '王宁汇总试用反馈。' + '讨论已结束。' * 80
        raw['overviewSources'] = [ids[1]]
        raw['speakerSummaries'] = [{'speakerId': 'speaker_00', 'name': '王宁', 'points': [], 'commitments': [{'text': '汇总试用反馈', 'sources': [ids[0]]}]}]
        raw['actions'][0]['task'] = '汇总试用反馈'
        result = validate(json.dumps(raw), snapshot)
        self.assertIn('王宁（00:00 发言，声纹匹配）', result['abstract'])
        self.assertIn(IDENTITY_NOTE, result['abstract'])
        self.assertEqual(result['speakerSummaries'][0]['name'], '王宁（声纹匹配，待确认）')
        self.assertIn(IDENTITY_NOTE, result['actions'][0]['task'])
        self.assertIsNone(result['actions'][0]['owner'])
        request = model_input(snapshot)
        self.assertEqual(request['segments'][0]['speaker']['name'], '王宁（声纹匹配，待确认）')
        self.assertEqual(snapshot['segments'][0]['speaker']['name'], '王宁')
        self.assertEqual(request['segments'][0]['text'], snapshot['segments'][0]['text'])
        raw['speakerSummaries'][0]['name'] = request['segments'][0]['speaker']['name']
        self.assertEqual(validate(json.dumps(raw), snapshot), result)
        raw['speakerSummaries'][0]['name'] = '王宁'
        current = settings()
        task = self.service.store.register(mid, snapshot, current, False)
        self.service.store.claim(task)
        self.service.store.complete(task, snapshot, current, result)
        self.assertEqual(self.service.get(mid)['result']['content'], result)
        hit = search(self.repo, {'text': '王宁汇总', 'from': None, 'to': None, 'offset': 0})['items'][0]['hit']
        self.assertIn('王宁（00:00 发言，声纹匹配）', hit['text'])
        self.assertIn(IDENTITY_NOTE, hit['text'])
        with self.repo.connect() as db:
            exported = '\n'.join(document_lines(db, mid, dict(scope='summary', format='txt', timestamps=False)))
        self.assertIn('王宁（声纹匹配，待确认）', exported)
        self.assertIn(IDENTITY_NOTE, exported)
        self.assertNotIn('private-member', exported)

        speakers.edit(mid, 'legacy', 0, speaker_id='speaker_00', name='王宁')
        self.assertTrue(self.service.get(mid)['result']['stale'])
        confirmed = self.service.store.snapshot(mid)
        self.assertNotEqual(confirmed['inputHash'], snapshot['inputHash'])
        self.assertEqual(model_input(confirmed)['segments'][0]['speaker']['name'], '王宁')
        self.assertEqual(validate(json.dumps(raw), confirmed), raw)
        plain = self.service.store.snapshot(mid, 'text')
        plain_raw = content(plain['segments'])
        self.assertEqual(validate(json.dumps(plain_raw), plain), plain_raw)
        self.assertTrue(all('speaker' not in item for item in model_input(plain)['segments']))

    def test_same_name_manual_identity_and_explicit_third_person_assignment_are_preserved(self):
        mid = seed(self.repo, 3)
        speakers, ids = self.speakers(mid)
        speakers.edit(mid, 'legacy', 0, speaker_id='speaker_01', name='陈甲')
        with self.repo.connect() as db:
            db.execute('UPDATE transcript_segments SET text=? WHERE id=?', ('请陈甲负责接口联调，我只提供账号。', ids[2]))
        snapshot = self.service.store.snapshot(mid)
        raw = content(snapshot['segments'])
        raw['topics'] = [{'text': '陈甲承诺提供账号', 'sources': [ids[1]]}, {'text': '原话：“请陈甲负责接口联调，我只提供账号。”', 'sources': [ids[2]]}]
        raw['speakerSummaries'] = [{'speakerId': 'speaker_01', 'name': '陈甲', 'points': [], 'commitments': [{'text': '提供账号', 'sources': [ids[1]]}]}]
        raw['actions'] = [{**raw['actions'][0], 'owner': '陈甲', 'sources': [identifier]} for identifier in ids]
        result = validate(json.dumps(raw), snapshot)
        self.assertEqual(result['topics'][0], raw['topics'][0])
        self.assertTrue(result['topics'][1]['text'].startswith(raw['topics'][1]['text']))
        self.assertEqual(result['speakerSummaries'][0]['name'], '陈甲')
        self.assertIsNone(result['actions'][0]['owner'])
        self.assertEqual(result['actions'][1]['owner'], '陈甲')
        self.assertEqual(result['actions'][2]['owner'], '陈甲')
        self.assertIn('陈甲（00:00 发言，声纹匹配）', result['abstract'])
        self.assertNotIn('speaker_01', result['abstract'])

    def test_mixed_automatic_and_manual_namesake_sources_keep_confirmed_owner(self):
        mid = seed(self.repo, 2)
        speakers, ids = self.speakers(mid)
        speakers.edit(mid, 'legacy', 0, speaker_id='speaker_01', name='陈甲')
        with self.repo.connect() as db:
            for identifier, text in zip(ids, ('需要完成接口联调。', '接口联调由我负责。')):
                db.execute('UPDATE transcript_segments SET text=? WHERE id=?', (text, identifier))
        snapshot = self.service.store.snapshot(mid)
        raw = content(snapshot['segments'])
        raw['actions'] = [{**raw['actions'][0], 'task': '接口联调', 'owner': '陈甲', 'sources': ids}]
        result = validate(json.dumps(raw), snapshot)
        self.assertEqual(result['actions'][0]['owner'], '陈甲')
        self.assertIn('00:00 发言，声纹匹配', result['actions'][0]['task'])
        self.assertNotIn('speaker_', result['abstract'])
        self.assertNotIn('speaker_', result['actions'][0]['task'])
        raw['actions'][0]['sources'] = [ids[0]]
        self.assertIsNone(validate(json.dumps(raw), snapshot)['actions'][0]['owner'])

    def test_identity_annotations_cannot_exceed_output_limits(self):
        mid = seed(self.repo, 2)
        self.speakers(mid)
        snapshot = self.service.store.snapshot(mid)
        raw = content(snapshot['segments'])
        for field, limit in (('title', 200), ('abstract', 4000)):
            oversized = copy.deepcopy(raw)
            oversized[field] = '陈甲' + '字' * (limit - 2)
            with self.assertRaises(DomainError):
                validate(json.dumps(oversized), snapshot)
        raw['topics'][0]['text'] = '字' * 1500
        with self.assertRaises(DomainError):
            validate(json.dumps(raw), snapshot)

    def test_new_search_export_and_optional_speaker_names(self):
        mid = seed(self.repo, 2)
        _, ids = self.speakers(mid)
        snapshot = self.service.store.snapshot(mid)
        value = content(snapshot['segments'])
        for field in ('agreements', 'disagreements', 'risks', 'openQuestions', 'suggestions'):
            value[field] = [{'text': field + '独特词', 'sources': [ids[0]]}]
        value['speakerSummaries'] = [{'speakerId': 'speaker_00', 'name': '陈甲', 'points': [{'text': '独特观点', 'sources': [ids[0]]}], 'commitments': [{'text': '独特承诺', 'sources': [ids[0]]}]}]
        value['actions'][0]['dependencies'] = '独特依赖'
        value['actions'][0]['blocker'] = '独特阻碍'
        current = settings()
        task = self.service.store.register(mid, snapshot, current, False)
        self.service.store.claim(task)
        self.service.store.complete(task, snapshot, current, value)
        for keyword, locator in [('独特承诺', 'speakerSummaries:0'), ('独特观点', 'speakerSummaries:0'), ('独特依赖', 'actions:0'), ('独特阻碍', 'actions:0')] + [(key + '独特词', key + ':0') for key in ('agreements', 'disagreements', 'risks', 'openQuestions', 'suggestions')]:
            hit = search(self.repo, {'text': keyword, 'from': None, 'to': None, 'offset': 0})['items'][0]['hit']
            self.assertEqual(hit['locator'], locator)
        with self.repo.connect() as db:
            full = '\n'.join(document_lines(db, mid, dict(scope='both', format='txt', timestamps=True)))
            plain = '\n'.join(document_lines(db, mid, dict(scope='transcript', format='txt', timestamps=False, speakers=False)))
        for text in ('AI 建议', '发言人摘要', '独特观点', '独特承诺', '独特依赖', '独特阻碍', '原文 [', '陈甲：'):
            self.assertIn(text, full)
        self.assertNotIn('陈甲', plain)
        self.assertNotIn('private-member', full)

    def test_schema8_additive_upgrade_backups_and_keeps_v1(self):
        self.service.shutdown()
        mid = seed(self.repo, 2)
        old = {'version': 1, 'title': '旧纪要', 'abstract': '旧概览', 'topics': ['旧讨论'], 'decisions': [], 'actions': [], 'risks': [], 'openQuestions': []}
        with self.repo.connect() as db:
            db.execute('INSERT INTO meeting_summaries (meetingId,taskId,inputHash,generatedAt,profileId,serviceName,model,parameters,sourceIncomplete,content) VALUES (?,?,?,?,?,?,?,?,?,?)', (mid, 'old-task', 'old-hash', 'old-date', 'old-profile', 'old-service', 'old-model', '{}', 0, json.dumps(old)))
            db.execute('INSERT INTO summary_attempts VALUES (?,?)', (mid, 'old-hash'))
            for table in ('summary_jobs', 'meeting_summaries'):
                for column in ('inputMode', 'speakerIncomplete', 'publication', 'inputSnapshot'):
                    db.execute(f'ALTER TABLE {table} DROP COLUMN {column}')
            db.execute('PRAGMA user_version=8')
        with patch('paa_core.summary_store.migrate_speaker_minutes', side_effect=sqlite3.OperationalError('test ddl failure')):
            with self.assertRaises(sqlite3.OperationalError):
                Repository(self.repo.root)
        self.assertTrue((self.repo.root / 'meetings.schema8.backup.sqlite3').exists())
        with self.repo.connect() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 8)
        self.repo = Repository(self.repo.root)
        self.service = MeetingSummary(self.repo, self.provider)
        self.service.configure(settings(), True)
        self.service.on_completed(mid)
        result = self.service.get(mid)['result']
        self.assertEqual(result['content'], old)
        self.assertEqual(result['inputMode'], 'text')
        self.assertFalse(result['stale'])
        self.assertEqual(self.provider.calls, [])
        with self.repo.connect() as db:
            exported = '\n'.join(document_lines(db, mid, dict(scope='summary', format='txt', timestamps=False)))
        self.assertIn('旧讨论', exported)


if __name__ == '__main__':
    unittest.main()
