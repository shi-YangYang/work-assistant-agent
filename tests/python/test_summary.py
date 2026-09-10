"""Isolated, bounded provider/schema/queue checks; never use real API credentials."""
import copy
import json
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/python'))
from paa_core.llm_provider import Provider, Limits, config, parameters
from paa_core.meeting_summary import MeetingSummary, validate
from paa_core.repository import Repository, DomainError
from paa_core.protocol import CoreService, handle
from paa_core.transcript_store import TranscriptStore
from test_recording import wait_for, FakeInput


def settings(url='https://example.com/v1', **changes):
    return {'profileId': str(uuid.uuid4()), 'revision': str(uuid.uuid4()), 'name': '服务甲',
            'baseUrl': url, 'apiKey': 'fake-private-test-key', 'model': 'unknown-kimi-next', 'stream': False,
            'parameters': {}, **changes}


def seed(repo, count=61):
    mid = str(uuid.uuid4())
    repo.create(mid, str(uuid.uuid4()))
    repo.update(mid, status='completed')
    with repo.connect() as db:
        db.execute('INSERT INTO transcription_jobs (meetingId,state,modelId,revision,config) VALUES (?,?,?,?,?)', (mid, 'completed', 'small', 'test', '{}'))
        chunk = str(uuid.uuid4())
        db.execute('INSERT INTO audio_chunks VALUES (?,?,?,?,?,?,?)', (chunk, mid, 0, 0, 1, 0, 1))
        for i in range(count):
            db.execute('INSERT INTO transcript_segments VALUES (?,?,?,?,?,?,?,?,?)',
                       (str(uuid.uuid4()), mid, chunk, i, i * 1000, i * 1000 + 500, '最后决定取消上线' if i == count - 1 else f'讨论 {i}', None, None))
    return mid


def content(segments):
    return {'version': 1, 'title': '上线安排', 'abstract': '最终取消上线。', 'topics': ['上线风险'],
            'decisions': [{'text': '取消上线', 'sources': [segments[-1]['id']]}],
            'actions': [{'task': '核对风险', 'owner': None, 'deadline': None, 'status': None, 'sources': [segments[0]['id']]}],
            'risks': [], 'openQuestions': []}


class FakeProvider(Provider):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.fail = False
    def complete(self, value, messages):
        self.payload(value, messages)
        self.calls.append((copy.deepcopy(value), messages))
        self.entered.set()
        if not self.release.wait(3):
            raise AssertionError('Test provider not released')
        if self.fail:
            raise DomainError('authentication', '测试认证失败')
        return json.dumps(content(json.loads(messages[-1]['content'])['segments']), ensure_ascii=False)


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Repository(Path(self.temp.name))
        self.provider = FakeProvider()
        self.service = MeetingSummary(self.repo, self.provider)
    def tearDown(self):
        self.provider.release.set()
        self.service.shutdown()
        self.temp.cleanup()
    def finish(self, mid, state='completed'):
        wait_for(lambda: self.service.get(mid)['task']['state'] == state)
        return self.service.get(mid)

    def test_full_ordered_snapshot_and_last_source_survive_failed_regeneration(self):
        mid = seed(self.repo)
        self.service.configure(settings(parameters={'thinking': {'type': 'enabled', 'budget': 1024}}), True)
        self.service.generate(mid)
        first = self.finish(mid)
        data = json.loads(self.provider.calls[0][1][-1]['content'])
        self.assertEqual(len(data['segments']), 61)
        self.assertEqual(data['segments'][-1]['text'], '最后决定取消上线')
        self.assertEqual(first['result']['content']['actions'][0]['owner'], None)
        self.assertEqual(first['result']['content']['decisions'][0]['sources'], [data['segments'][-1]['id']])
        self.provider.fail = True
        self.service.generate(mid)
        failed = self.finish(mid, 'failed')
        self.assertEqual(failed['result'], first['result'])
        self.assertNotIn('fake-private', self.repo.database.read_bytes().decode('utf8', errors='ignore'))

    def test_new_completion_only_idempotent_and_no_startup_or_config_scan(self):
        mid = seed(self.repo)
        self.service.configure(settings(), True)
        self.assertIsNone(self.service.get(mid)['task'])
        self.service.on_completed(mid)
        self.finish(mid)
        self.service.on_completed(mid)
        self.service.configure(settings(), True)
        self.assertEqual(len(self.provider.calls), 1)
        self.service.shutdown()
        self.service = MeetingSummary(self.repo, self.provider)
        self.service.configure(settings(), True)
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(self.service.get(mid)['task']['state'], 'completed')
        missing = seed(self.repo)
        self.service.configure(None, True)
        self.service.on_completed(missing)
        self.service.configure(settings(), True)
        self.service.on_completed(missing)
        self.assertIsNone(self.service.get(missing)['task'])
        self.service.generate(missing)
        self.finish(missing)

    def test_completion_hook_is_core_side_for_state_and_final_commit(self):
        mid = seed(self.repo)
        with self.repo.connect() as db:
            db.execute("UPDATE transcription_jobs SET state='running' WHERE meetingId=?", (mid,))
        store = TranscriptStore(self.repo)
        store.on_completed = self.service.on_completed
        self.service.configure(settings(), True)
        store.state(mid, 'completed')
        self.finish(mid)
        self.assertEqual(len(self.provider.calls), 1)

    def test_cancel_queued_on_selection_disable_and_inflight_keeps_snapshot(self):
        first, second = seed(self.repo), seed(self.repo)
        old = settings()
        self.service.configure(old, True)
        self.provider.release.clear()
        self.service.generate(first)
        self.assertTrue(self.provider.entered.wait(1))
        self.service.generate(first)
        self.service.on_completed(second)
        self.service.configure(settings(name='服务乙'), True)
        self.assertEqual(self.service.get(second)['task']['state'], 'interrupted')
        self.provider.release.set()
        self.finish(first)
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(self.provider.calls[0][0], old)
        third, fourth = seed(self.repo), seed(self.repo)
        self.provider.release.clear(); self.provider.entered.clear()
        current = settings()
        self.service.configure(current, True)
        self.service.generate(third)
        self.assertTrue(self.provider.entered.wait(1))
        self.service.on_completed(fourth)
        self.service.configure(current, False)
        self.assertEqual(self.service.get(fourth)['task']['state'], 'interrupted')
        self.provider.release.set()
        self.finish(third)

    def test_shutdown_is_bounded_and_late_result_cannot_overwrite_interruption(self):
        mid = seed(self.repo)
        self.service.configure(settings(), True)
        self.provider.release.clear()
        self.service.generate(mid)
        self.assertTrue(self.provider.entered.wait(1))
        started = time.monotonic()
        self.service.shutdown()
        self.assertLess(time.monotonic() - started, .5)
        self.provider.release.set(); self.service.thread.join(1)
        self.assertEqual(self.service.get(mid)['task']['state'], 'interrupted')
        self.assertIsNone(self.service.get(mid)['result'])
        self.service = MeetingSummary(self.repo, self.provider)
        self.assertEqual(self.service.get(mid)['task']['state'], 'interrupted')

    def test_empty_incomplete_and_oversized_input_never_succeed(self):
        self.service.configure(settings(), True)
        empty = seed(self.repo, 0)
        with self.assertRaisesRegex(DomainError, '没有可整理'): self.service.generate(empty)
        mid = seed(self.repo)
        with self.repo.connect() as db: db.execute("UPDATE transcription_jobs SET state='paused' WHERE meetingId=?", (mid,))
        with self.assertRaisesRegex(DomainError, '先完成'): self.service.generate(mid)
        with self.repo.connect() as db: db.execute("UPDATE transcription_jobs SET state='completed' WHERE meetingId=?", (mid,))
        self.provider.limits.request = 100
        self.service.generate(mid)
        self.finish(mid, 'failed')
        self.assertEqual(len(self.provider.calls), 0)

    def test_invalid_summary_references_fields_truncation_and_fences(self):
        snapshot = self.service.store.snapshot(seed(self.repo))
        good = content(snapshot['segments'])
        self.assertEqual(validate('```json\n' + json.dumps(good) + '\n```', snapshot), good)
        cases = []
        bad = copy.deepcopy(good); bad['actions'][0]['owner'] = 7; cases.append(bad)
        bad = copy.deepcopy(good); bad['decisions'][0]['sources'] = ['missing']; cases.append(bad)
        bad = copy.deepcopy(good); bad['extra'] = 'not allowed'; cases.append(bad)
        bad = copy.deepcopy(good); bad['version'] = True; cases.append(bad)
        for value in cases:
            with self.assertRaises(DomainError): validate(json.dumps(value), snapshot)
        with self.assertRaises(DomainError): validate('Here: ' + json.dumps(good), snapshot)

    def test_schema2_backup_and_failed_migration_rolls_back(self):
        self.service.shutdown()
        mid = seed(self.repo)
        with self.repo.connect() as db:
            for table in ('meeting_summaries', 'summary_jobs', 'summary_attempts'): db.execute('DROP TABLE ' + table)
            db.execute('PRAGMA user_version=2')
        with patch('paa_core.summary_store.migrate', side_effect=sqlite3.OperationalError('test failure')):
            with self.assertRaises(sqlite3.OperationalError): Repository(self.repo.root)
        with self.repo.connect() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT count(*) FROM transcript_segments').fetchone()[0], 61)
        self.assertTrue((self.repo.root / 'meetings.schema2.backup.sqlite3').exists())
        upgraded = Repository(self.repo.root)
        with upgraded.connect() as db: self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 3)
        self.assertEqual(upgraded.get(mid)['status'], 'completed')
        self.service = MeetingSummary(upgraded, self.provider)

    def test_operation_pagination_cancellation_and_storage_claim_failure_keep_worker_alive(self):
        config_a = settings()
        with patch.object(self.provider, 'models', return_value={'models': [{'id': f'm{i}', 'selectable': True} for i in range(61)], 'updatedAt': 1}):
            operation = self.service.operation('models', config_a)['id']
            wait_for(lambda: self.service.operation_status(operation)['state'] == 'completed')
            self.assertEqual(len(self.service.operation_status(operation)['result']['models']), 50)
            self.assertEqual(len(self.service.operation_status(operation, 50)['result']['models']), 11)
            self.service.cancel_operations(config_a['profileId'])
            with self.assertRaises(DomainError): self.service.operation_status(operation)
        mid = seed(self.repo)
        self.service.configure(config_a, True)
        with patch.object(self.service.store, 'claim', side_effect=sqlite3.OperationalError('test lock')):
            self.service.generate(mid)
            self.finish(mid, 'failed')
        self.assertTrue(self.service.thread.is_alive())
        self.service.generate(mid)
        self.finish(mid)

    def test_refresh_blocks_current_manual_and_automatic_generation_without_request(self):
        current = settings(model='embedding-only')
        self.service.configure(current, True)
        with patch.object(self.provider, '_models', return_value={'models': [{'id': 'embedding-only', 'selectable': False}], 'updatedAt': 1}):
            self.provider.models(current)
        mid = seed(self.repo)
        with self.assertRaises(DomainError): self.service.generate(mid)
        with self.assertRaises(DomainError): self.service.operation('check', current)
        # Use the real Provider guard at the outbound boundary for the automatic path.
        with patch.object(self.provider, 'complete', wraps=lambda value, messages: Provider.complete(self.provider, value, messages)):
            self.service.on_completed(mid)
            result = self.finish(mid, 'failed')
        self.assertEqual(result['task']['errorCode'], 'nontext_model')
        self.assertEqual(self.provider.calls, [])

    def test_core_controls_remain_responsive_during_slow_model(self):
        core = CoreService(self.repo.root, source=FakeInput(), summary_provider=self.provider)
        try:
            mid = seed(core.repository)
            core.summary.configure(settings(), True)
            self.provider.release.clear()
            core.summary.generate(mid)
            self.assertTrue(self.provider.entered.wait(1))
            started = time.monotonic()
            result, _ = handle({'id': 'a', 'method': 'recording.start', 'params': {'operationId': str(uuid.uuid4())}}, core)
            self.assertIn('result', result)
            result, _ = handle({'id': 'b', 'method': 'recording.status'}, core)
            self.assertIn('result', result)
            self.assertLess(time.monotonic() - started, 1)
        finally:
            self.provider.release.set()
            core.summary.shutdown(); core.transcription.shutdown(); core.recorder.shutdown()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_GET(self): self.do_POST()
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self.server.calls.append((self.path, self.headers.get('Authorization'), json.loads(body) if body else None))
        time.sleep(self.server.delay)
        self.send_response(self.server.status)
        self.send_header('Content-Length', str(len(self.server.payload)))
        self.end_headers()
        try:
            if self.server.partial_stall:
                time.sleep(.4)
                self.wfile.write(self.server.payload[:1])
                self.wfile.flush()
                self.server.release.wait(2)
                self.wfile.write(self.server.payload[1:])
            else:
                self.wfile.write(self.server.payload)
        except (BrokenPipeError, ConnectionResetError): pass


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.server.calls = []; self.server.delay = 0; self.server.status = 200
        self.server.partial_stall = False; self.server.release = threading.Event()
        self.server.payload = json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': 'OK'}}]}).encode()
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .02}, daemon=True); self.thread.start()
        self.provider = Provider(Limits(connect=.05, deadline=.6), allow_loopback=True)
        self.config = settings(f'http://127.0.0.1:{self.server.server_port}/v1')
    def tearDown(self):
        self.server.release.set()
        self.server.shutdown(); self.server.server_close(); self.thread.join(1)
    def test_draft_models_and_check_share_parameters_without_inventing_capability(self):
        self.server.payload = json.dumps({'data': [{'id': 'new-model'}, {'id': 'new-model'}, {'id': 'embedding', 'type': 'embedding'}]}).encode()
        values = self.provider.models({**self.config, 'model': ''})
        self.assertEqual(values['models'], [{'id': 'embedding', 'selectable': False}, {'id': 'new-model', 'selectable': True}])
        self.server.payload = json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': 'OK'}}]}).encode()
        self.config['parameters'] = {'thinking': {'enabled': True, 'budget': 2048}, 'reasoning_effort': 'future-ultra'}
        self.provider.check(self.config)
        self.assertEqual(self.server.calls[0][0], '/v1/models')
        self.assertEqual(self.server.calls[1][0], '/v1/chat/completions')
        self.assertEqual(self.server.calls[1][2]['thinking'], {'enabled': True, 'budget': 2048})
        self.assertEqual(self.server.calls[1][2]['reasoning_effort'], 'future-ultra')
        self.assertEqual(self.server.calls[1][1], 'Bearer fake-private-test-key')
    def test_separate_connect_and_total_deadline_and_safe_errors(self):
        self.server.delay = .12
        self.provider.check(self.config)  # Response may take longer than the connection timeout.
        self.provider.limits.deadline = .03
        with self.assertRaises(DomainError) as caught: self.provider.check(self.config)
        self.assertEqual(caught.exception.code, 'network_timeout')
        self.assertNotIn(self.config['apiKey'], str(caught.exception))
    def test_partial_response_stall_respects_one_total_deadline_without_retry(self):
        self.server.partial_stall = True
        self.provider.limits.deadline = .5
        started = time.monotonic()
        with self.assertRaises(DomainError) as caught:
            self.provider.check(self.config)
        self.assertEqual(caught.exception.code, 'network_timeout')
        # Allow 150 ms for CI scheduling, but not a fresh 500 ms after the first byte.
        self.assertLess(time.monotonic() - started, .65)
        self.assertEqual(len(self.server.calls), 1)

    def test_stalled_dns_is_bounded_without_retries_and_recovers_after_late_completion(self):
        release = threading.Event()
        original = socket.getaddrinfo
        hostname = {**self.config, 'baseUrl': f'http://localhost:{self.server.server_port}/v1'}
        self.provider.limits.deadline = .1

        def delayed(*args, **kwargs):
            if not release.wait(2):
                raise AssertionError('Test DNS was not released')
            # Resolve to this IPv4-only fixture, independent of OS localhost ordering.
            return original('127.0.0.1', *args[1:], **kwargs)

        with patch('socket.getaddrinfo', side_effect=delayed) as lookup:
            try:
                for _ in range(3):
                    started = time.monotonic()
                    with self.assertRaises(DomainError) as caught:
                        self.provider.check(hostname)
                    self.assertEqual(caught.exception.code, 'network_timeout')
                    # Includes asyncio.run cleanup; no wait for the blocked OS call.
                    self.assertLess(time.monotonic() - started, .25)
                self.assertEqual(lookup.call_count, 1)
                self.assertEqual(self.server.calls, [])
                thread = self.provider.resolver.thread
                self.assertTrue(thread.is_alive())
                self.assertTrue(thread.daemon)
                # A stalled hostname does not occupy the network worker or block IPs.
                self.provider.limits.deadline = .6
                self.provider.check(self.config)
                self.assertEqual(lookup.call_count, 1)
                self.assertEqual(len(self.server.calls), 1)
            finally:
                release.set()
                self.provider.resolver.thread.join(1)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(self.server.calls), 1)  # Late DNS did not send a request.
            self.provider.check(hostname)
            self.assertEqual(lookup.call_count, 2)
            self.assertEqual(len(self.server.calls), 2)

    def test_known_nontext_metadata_is_trusted_scoped_refreshable_and_bounded(self):
        self.server.payload = b'{"data":[{"id":"embedding-only","type":"embedding"}]}'
        blocked = {**self.config, 'model': 'embedding-only'}
        self.provider.models(self.config)
        for call in (lambda: self.provider.assert_text_model(blocked), lambda: self.provider.check(blocked),
                     lambda: self.provider.complete(blocked, [{'role': 'user', 'content': 'test'}])):
            with self.assertRaises(DomainError) as caught: call()
            self.assertEqual(caught.exception.code, 'nontext_model')
        self.assertEqual(len(self.server.calls), 1)
        for changes in ({'model': 'unknown-manual'}, {'profileId': str(uuid.uuid4())},
                        {'baseUrl': self.config['baseUrl'] + '/other'}, {'apiKey': 'different-fake-key'}):
            self.provider.assert_text_model({**blocked, **changes})
        self.server.status = 401
        with self.assertRaises(DomainError): self.provider.models(self.config)
        with self.assertRaises(DomainError): self.provider.assert_text_model(blocked)
        self.server.status = 200
        self.server.payload = b'{"data":[{"id":"embedding-only","output_modalities":["text"]}]}'
        self.provider.models(self.config)
        self.provider.assert_text_model(blocked)
        self.server.payload = b'{"data":[{"id":"embedding-only","type":"embedding"}]}'
        self.provider.models(self.config)
        self.provider.forget_models(self.config['profileId'])
        self.provider.assert_text_model(blocked)
        with patch.object(self.provider, '_models', return_value={'models': [{'id': 'embedding-only', 'selectable': False}], 'updatedAt': 1}):
            for _ in range(33): self.provider.models(settings())
        self.assertEqual(len(self.provider.directories), 32)

    def test_http_errors_redirect_and_oversized_reply_do_not_retry(self):
        for status, code in [(401,'authentication'), (403,'permission'), (429,'quota'), (302,'redirect'), (400,'request_rejected')]:
            self.server.status = status
            with self.assertRaises(DomainError) as caught: self.provider.check(self.config)
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(len(self.server.calls), 5)
        self.server.status = 200; self.provider.limits.response = 4
        with self.assertRaises(DomainError) as caught: self.provider.check(self.config)
        self.assertEqual(caught.exception.code, 'response_too_large')
    def test_sse_requires_content_normal_stop_and_terminal_event(self):
        self.config['stream'] = True
        events = [{'choices': [{'delta': {'reasoning_content': 'private chain'}, 'finish_reason': None}]},
                  {'choices': [{'delta': {'content': 'OK'}, 'finish_reason': None}]},
                  {'choices': [{'delta': {}, 'finish_reason': 'stop'}]}]
        body = b''.join(('data: ' + json.dumps(item) + '\n\n').encode() for item in events)
        self.server.payload = body + b'data: [DONE]\n\n'
        self.assertEqual(self.provider.complete(self.config, [{'role':'user','content':'test'}]), 'OK')
        for data in (body, body.replace(b'"stop"', b'"length"') + b'data: [DONE]\n\n', b'data: [DONE]\n\n'):
            self.server.payload = data
            with self.assertRaises(DomainError): self.provider.check(self.config)
    def test_alibaba_metadata_pagination_and_same_origin(self):
        source = settings('https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1')
        pages = [{'output': {'models': [{'model': f'qwen-{i}'} for i in range(100)]}},
                 {'output': {'models': [{'model': 'image-only', 'inference_metadata': {'response_modality': ['Image']}}]}}]
        with patch.object(self.provider, 'request', side_effect=[json.dumps(item).encode() for item in pages]) as request:
            result = self.provider.models(source)
            self.assertEqual(request.call_count, 2)
            self.assertEqual(request.call_args.args[0]['baseUrl'], 'https://cn-hongkong.dashscope.aliyuncs.com')
            self.assertEqual(request.call_args.args[1], '/api/v1/models')
            self.assertFalse(result['models'][0]['selectable'])
        with patch.object(self.provider, 'request', return_value=b'{"data":[]}') as request:
            self.provider.models(settings('https://dashscope.aliyuncs.com.attacker.test/v1'))
            self.assertEqual(request.call_args.args[1], '/models')
    def test_reject_protected_parameters_and_bad_urls(self):
        for value in ({'model':'changed'}, {'thinking': {'authorization':'secret'}}, {'constructor': {}}, {'thinking': {'template': '${secret}'}}, {'reasoning_effort': float('nan')}):
            with self.assertRaises(DomainError): parameters(value)
        parameters({'reasoning_effort': 'unknown-strength', 'thinking': {'enabled': True, 'budget': 99, 'level': None}})
        for url in ('http://example.com/v1', 'https://user:pass@example.com/v1', 'https://example.com/v1?key=a'):
            with self.assertRaises(DomainError): config(settings(url))


if __name__ == '__main__': unittest.main()
