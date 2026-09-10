"""Bounded UTF-8 JSON Lines controls. Recording and finalization run off this loop."""
from __future__ import annotations

import json
import os
import platform
import sqlite3
from pathlib import Path
from typing import BinaryIO

from .recorder import Recorder
from .repository import ACTIVE, DomainError, Repository, valid_id
from .transcription import Transcription
from .meeting_summary import MeetingSummary
from .llm_provider import Provider

MAX_LINE_BYTES = 65_536


class CoreService:
    def __init__(self, root: Path | None, source=None, transcription_factory=Transcription, summary_provider=None):
        self.repository = None
        self.recorder = None
        self.storage_error = None
        self.transcription = None
        self.summary = None
        if root is not None:
            try:
                self.repository = Repository(root)
                self.recorder = Recorder(self.repository, source=source)
                self.transcription = transcription_factory(self.repository, self.recorder)
                self.summary = MeetingSummary(self.repository, summary_provider or Provider(allow_loopback=bool(os.environ.get('PAA_TEST_DATA_DIR')) and os.environ.get('PAA_TEST_ALLOW_HTTP') == '1'))
                if hasattr(self.transcription, "store"):
                    self.transcription.store.on_completed = self.summary.on_completed
            except (OSError, sqlite3.Error, DomainError):
                self.storage_error = '无法打开会议存储，请检查数据目录权限、磁盘空间和数据库版本；不要删除已有数据。'

    def dispatch(self, method: str, params: dict):
        expected = {'recording.start': {'operationId'}, 'recording.stop': {'meetingId'},
                    'recording.interrupt': {'meetingId'}, 'meetings.get': {'meetingId'},
                    'meetings.list': set(), 'transcription.start': {'meetingId'},
                    'transcription.status': {'meetingId'}, 'transcript.list': {'meetingId', 'cursor'},
                    'summary.validateModel': {'config'}, 'summary.forgetModels': {'profileId'},
                    'summary.configure': {'config', 'automatic'}, 'summary.generate': {'meetingId'},
                    'summary.get': {'meetingId'}, 'summary.operation': {'kind', 'config'},
                    'summary.operationStatus': {'id', 'offset'}, 'summary.source': {'meetingId', 'segmentId'}, 'summary.cancelOperations': {'profileId'}}
        keys = expected.get(method, set())
        if method == 'meetings.list' and set(params) == {'offset'}:
            if type(params['offset']) is not int or not 0 <= params['offset'] <= 1_000_000:
                raise DomainError('invalid_params', '分页位置无效。')
        elif set(params) != keys:
            raise DomainError('invalid_params', '请求参数无效。')
        if 'meetingId' in params and not valid_id(params['meetingId']):
            raise DomainError('invalid_params', '会议标识无效。')
        if method == 'transcript.list' and (type(params['cursor']) is not int or not -1 <= params['cursor'] <= 1_000_000_000):
            raise DomainError('invalid_params', '文字分页位置无效。')
        if method.startswith('summary.'):
            if not self.summary:
                raise DomainError('storage_unavailable', self.storage_error or '存储尚未配置。')
            if method == 'summary.configure':
                result = self.summary.configure(params['config'], params['automatic'])
            elif method == 'summary.validateModel':
                result = self.summary.provider.assert_text_model(params['config'])
            elif method == 'summary.forgetModels':
                if not valid_id(params['profileId']):
                    raise DomainError('invalid_params', '服务标识无效。')
                self.summary.provider.forget_models(params['profileId'])
                result = {'forgotten': True}
            elif method == 'summary.generate':
                result = self.summary.generate(params['meetingId'])
            elif method == 'summary.get':
                result = self.summary.get(params['meetingId'])
            elif method == 'summary.operation':
                result = self.summary.operation(params['kind'], params['config'])
            elif method == 'summary.cancelOperations':
                if not valid_id(params['profileId']):
                    raise DomainError('invalid_params', '服务标识无效。')
                result = self.summary.cancel_operations(params['profileId'])
            elif method == 'summary.operationStatus':
                if not valid_id(params['id']) or type(params['offset']) is not int or not 0 <= params['offset'] <= 2000:
                    raise DomainError('invalid_params', '操作标识或分页位置无效。')
                result = self.summary.operation_status(params['id'], params['offset'])
            elif method == 'summary.source':
                if not isinstance(params['segmentId'], str) or len(params['segmentId']) > 64:
                    raise DomainError('invalid_params', '原文片段无效。')
                with self.repository.lock, self.repository.connect() as db:
                    row = db.execute('SELECT id,startMs,endMs,text FROM transcript_segments WHERE meetingId=? AND id=?', (params['meetingId'], params['segmentId'])).fetchone()
                if not row:
                    raise DomainError('source_missing', '未找到原文片段。')
                result = dict(row)
            else:
                raise DomainError('method_not_found', 'Unknown method')
            return result, False
        if method == 'health':
            return {'pythonVersion': platform.python_version(), 'processId': os.getpid(),
                    'storageError': self.storage_error,
                    'capabilities': [{'id': 'recording', 'available': bool(self.recorder and not self.recorder.dependency_error)},
                                     {'id': 'transcription', 'available': bool(self.transcription and self.transcription.model.status()['state'] == 'ready')}, {'id': 'summary', 'available': bool(self.summary and self.summary.settings)}]}, False
        if method == 'shutdown':
            if self.recorder and self.recorder.status()['state'] in ACTIVE:
                raise DomainError('recording_active', '录音尚未完成保存，不能退出。')
            if self.summary:
                self.summary.shutdown()
            if self.transcription:
                self.transcription.shutdown()
            return {'stopping': True}, True
        if method in ('model.status', 'model.download', 'model.cancel', 'transcription.start', 'transcription.status', 'transcription.activity', 'transcription.pause', 'transcript.list'):
            if not self.transcription:
                raise DomainError('storage_unavailable', self.storage_error or '存储尚未配置。')
            actions = {'model.status': self.transcription.model.status,
                       'model.download': self.transcription.model.download,
                       'model.cancel': self.transcription.model.cancel,
                       'transcription.activity': self.transcription.activity,
                       'transcription.pause': self.transcription.pause}
            if method in actions:
                return actions[method](), False
            if method == 'transcript.list':
                return self.transcription.store.page(params['meetingId'], params['cursor']), False
            return (self.transcription.start(params['meetingId']) if method == 'transcription.start' else self.transcription.status(params['meetingId'])), False
        if method not in ('recording.start', 'recording.status', 'recording.stop', 'recording.interrupt', 'meetings.list', 'meetings.get'):
            raise DomainError('method_not_found', 'Unknown method')
        if not self.repository or not self.recorder:
            raise DomainError('storage_unavailable', self.storage_error or '会议存储尚未配置。')
        if method == 'recording.start':
            result = self.recorder.start(params['operationId'])
            if self.transcription and result['meetingId']:
                self.transcription.auto_start(result['meetingId'])
        elif method == 'recording.status':
            result = self.recorder.status()
        elif method in ('recording.stop', 'recording.interrupt'):
            result = self.recorder.stop(params['meetingId'], 'system_suspend' if method == 'recording.interrupt' else None)
            if method == 'recording.interrupt' and self.transcription:
                self.transcription.pause()
        elif method == 'meetings.list':
            result = self.repository.list(params.get('offset', 0))
        else:
            result = self.repository.get(params['meetingId'], internal=True)
        return result, False


def error(request_id, code, message):
    return {'id': request_id, 'error': {'code': code, 'message': message}}


def handle(request: object, service: CoreService | None = None) -> tuple[dict, bool]:
    if not isinstance(request, dict):
        return error(None, 'invalid_request', 'Request must be an object'), False
    request_id = request.get('id')
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
        return error(None, 'invalid_request', 'A short string id is required'), False
    if set(request) - {'id', 'method', 'params'} or not isinstance(request.get('method'), str):
        return error(request_id, 'invalid_request', 'Invalid request structure'), False
    params = request.get('params', {})
    if not isinstance(params, dict):
        return error(request_id, 'invalid_params', 'Expected an object'), False
    try:
        result, stopping = (service or CoreService(None)).dispatch(request['method'], params)
        return {'id': request_id, 'result': result}, stopping
    except DomainError as exc:
        return error(request_id, exc.code, str(exc)), False
    except (OSError, sqlite3.Error):
        return error(request_id, 'storage_error', '无法读写会议存储，请检查磁盘空间、目录权限或数据库占用。'), False
    except Exception:
        return error(request_id, 'core_error', '本地核心无法完成此操作，请保留数据并重新连接。'), False


def serve(source: BinaryIO, destination: BinaryIO, service: CoreService | None = None):
    try:
        while True:
            line = source.readline(MAX_LINE_BYTES + 1)
            if not line:
                return
            if len(line) > MAX_LINE_BYTES:
                while not line.endswith(b'\n'):
                    line = source.readline(MAX_LINE_BYTES + 1)
                    if not line:
                        break
                response, stopping = error(None, 'invalid_request', 'Request is too large'), False
            else:
                try:
                    request = json.loads(line.decode('utf-8'))
                except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
                    response, stopping = error(None, 'invalid_json', 'Expected UTF-8 JSON'), False
                else:
                    response, stopping = handle(request, service)
            encoded = (json.dumps(response, ensure_ascii=False) + '\n').encode('utf-8')
            if len(encoded) > MAX_LINE_BYTES:
                encoded = (json.dumps(error(response.get('id'), 'response_too_large', '返回内容超限，请缩小请求范围。'), ensure_ascii=False) + '\n').encode('utf-8')
            destination.write(encoded)
            destination.flush()
            if stopping:
                return
    finally:
        if service and service.summary:
            service.summary.shutdown()
        if service and service.transcription:
            service.transcription.shutdown()
        if service and service.recorder:
            service.recorder.shutdown()
