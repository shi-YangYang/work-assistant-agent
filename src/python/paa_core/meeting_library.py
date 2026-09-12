"""Bounded background search and immutable, chunked text snapshots."""
from __future__ import annotations

import base64
import copy
import json
import queue
import sqlite3
import tempfile
import threading
import time
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path

from .repository import ACTIVE, DomainError


def summary_fields(content):
    for key in ('title', 'abstract'):
        yield key, content.get(key, '')
    for key in ('topics', 'risks', 'openQuestions'):
        for index, value in enumerate(content.get(key, [])):
            yield f'{key}:{index}', value
    for index, item in enumerate(content.get('decisions', [])):
        yield f'decisions:{index}', item['text']
    for index, item in enumerate(content.get('actions', [])):
        yield f'actions:{index}', ' · '.join([item['task'], '负责人：' + (item.get('owner') or '待确认'), '截止：' + (item.get('deadline') or '待确认'), '状态：' + (item.get('status') or '待确认')])


def fold(text):
    return text.translate(str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'))


def preview(text, keyword):
    start = fold(text).find(fold(keyword))
    left = max(0, start - 45)
    right = max(left + 180, start + len(keyword) + 45)
    return ('…' if left else '') + text[left:right] + ('…' if len(text) > right else '')


def validate_query(value):
    if not isinstance(value, dict) or set(value) != {'text', 'from', 'to', 'offset'} or not isinstance(value['text'], str) or len(value['text']) > 200 or type(value['offset']) is not int or not 0 <= value['offset'] <= 1_000_000:
        raise DomainError('invalid_query', '搜索条件无效。')
    for key in ('from', 'to'):
        if value[key] is not None:
            try:
                stamp = datetime.fromisoformat(value[key])
                if stamp.tzinfo is None:
                    raise ValueError()
            except (ValueError, TypeError):
                raise DomainError('invalid_query', '日期范围无效。') from None
    if value['from'] and value['to'] and datetime.fromisoformat(value['from']) >= datetime.fromisoformat(value['to']):
        raise DomainError('invalid_query', '开始日期不能晚于结束日期。')
    return {**value, 'text': value['text'].strip()}


def search(repo, value):
    value = validate_query(value)
    keyword = value['text']
    deadline = time.monotonic() + 2
    with repo.connect() as db:
        db.execute('PRAGMA query_only=ON')
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        db.create_function('summary_matches', 1, lambda raw: int(any(fold(keyword) in fold(text) for _, text in summary_fields(json.loads(raw)))))
        escaped = keyword.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        args = [value['from'], value['from'], value['to'], value['to']]
        where = "(? IS NULL OR julianday(COALESCE(m.startedAt,m.createdAt))>=julianday(?)) AND (? IS NULL OR julianday(COALESCE(m.startedAt,m.createdAt))<julianday(?))"
        if keyword:
            where += " AND (m.title LIKE ? ESCAPE '\\' OR EXISTS(SELECT 1 FROM transcript_segments t WHERE t.meetingId=m.id AND t.text LIKE ? ESCAPE '\\') OR EXISTS(SELECT 1 FROM meeting_summaries s WHERE s.meetingId=m.id AND summary_matches(s.content)))"
            args.extend([f'%{escaped}%', f'%{escaped}%'])
        db.execute('BEGIN')
        try:
            rows = db.execute(f'''SELECT m.*,d.meetingId IS NOT NULL AS deleting,d.error AS deletionError FROM meetings m
                LEFT JOIN meeting_deletions d ON m.id=d.meetingId WHERE {where}
                ORDER BY julianday(COALESCE(m.startedAt,m.createdAt)) DESC,m.id DESC LIMIT 26 OFFSET ?''', (*args, value['offset'])).fetchall()
            values = []
            for row in rows[:25]:
                hit = None
                if keyword and not row['deleting']:
                    if fold(keyword) in fold(row['title']):
                        hit = {'source': 'title', 'text': preview(row['title'], keyword)}
                    else:
                        segment = db.execute("SELECT id,text,startMs FROM transcript_segments WHERE meetingId=? AND text LIKE ? ESCAPE '\\' ORDER BY sequence LIMIT 1", (row['id'], f'%{escaped}%')).fetchone()
                        if segment:
                            hit = {'source': 'transcript', 'text': preview(segment['text'], keyword), 'segmentId': segment['id'], 'startMs': segment['startMs']}
                        else:
                            summary = db.execute('SELECT generatedAt,content FROM meeting_summaries WHERE meetingId=?', (row['id'],)).fetchone()
                            if summary:
                                for locator, text in summary_fields(json.loads(summary['content'])):
                                    if fold(keyword) in fold(text):
                                        hit = {'source': 'summary', 'text': preview(text, keyword), 'locator': locator, 'generatedAt': summary['generatedAt']}
                                        break
                values.append({'meeting': repo.present(dict(row)), 'hit': hit})
            return {'items': values, 'hasMore': len(rows) > 25}
        except sqlite3.OperationalError as exc:
            if 'interrupted' in str(exc):
                raise DomainError('search_timeout', '搜索范围较大，请缩小日期范围后重试。') from None
            raise


def timestamp(ms):
    seconds = ms // 1000
    return f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'


def escape_markdown(text):
    import re
    return re.sub(r'([\\`*_{}\[\]()#+.!<>|~-])', r'\\\1', text)


def document_lines(db, meeting_id, options):
    meeting = db.execute('SELECT * FROM meetings WHERE id=?', (meeting_id,)).fetchone()
    if not meeting:
        raise DomainError('meeting_missing', '未找到这场会议。')
    if meeting['status'] in ACTIVE or db.execute('SELECT 1 FROM meeting_deletions WHERE meetingId=?', (meeting_id,)).fetchone():
        raise DomainError('meeting_busy', '请在会议结束并保存后导出。')
    summary = db.execute('SELECT * FROM meeting_summaries WHERE meetingId=?', (meeting_id,)).fetchone()
    count = db.execute('SELECT COUNT(*) FROM transcript_segments WHERE meetingId=?', (meeting_id,)).fetchone()[0]
    transcription = db.execute('SELECT state FROM transcription_jobs WHERE meetingId=?', (meeting_id,)).fetchone()
    if options['scope'] in ('summary', 'both') and not summary or options['scope'] in ('transcript', 'both') and not count:
        raise DomainError('content_missing', '尚无所选内容，请调整导出范围。')
    md = options['format'] == 'md'
    text = escape_markdown if md else str
    def heading(label, level=2): return ('#' * level + ' ' if md else '') + text(label)
    yield heading(meeting['title'], 1)
    yield f"日期：{meeting['startedAt'] or meeting['createdAt']}"
    yield f"时长：{timestamp(meeting['durationMs'])}"
    if meeting['status'] != 'completed':
        yield '资料不完整：录音曾中断或未成功保存，仅包含已保留内容。'
    if options['scope'] in ('summary', 'both'):
        yield ''
        yield heading('会议纪要')
        yield f"生成时间：{summary['generatedAt']}"
        if summary['sourceIncomplete']:
            yield '纪要资料不完整：仅依据保留下来的内容。'
        content = json.loads(summary['content'])
        yield heading(content['title'], 3)
        yield text(content['abstract'])
        for key, label in (('topics', '讨论要点'), ('decisions', '明确决策'), ('actions', '行动项'), ('risks', '风险'), ('openQuestions', '待确认问题')):
            yield ''
            yield heading(label, 3)
            values = [value for locator, value in summary_fields(content) if locator.startswith(key + ':')]
            for value in values or ['未提及']:
                yield ('- ' if md else '• ') + text(value)
    if options['scope'] in ('transcript', 'both'):
        yield ''
        yield heading('文字记录')
        if not transcription or transcription['state'] != 'completed':
            yield '文字记录尚未完成：本次导出仅包含快照时已保存的片段。'
        for segment in db.execute('SELECT startMs,endMs,text FROM transcript_segments WHERE meetingId=? ORDER BY sequence', (meeting_id,)):
            prefix = f"[{timestamp(segment['startMs'])} – {timestamp(segment['endMs'])}] " if options['timestamps'] else ''
            yield text(prefix + segment['text'])


class MeetingLibrary:
    def __init__(self, repo):
        self.repo = repo
        self.lock = threading.RLock()
        self.operations = {}
        self.queue = queue.Queue(maxsize=8)
        self.stopped = False
        self.thread = None

    def start(self, kind, params):
        if kind == 'search':
            params = validate_query(params)
        elif kind == 'export':
            if set(params) != {'meetingId', 'format', 'scope', 'timestamps'} or params['format'] not in ('md', 'txt') or params['scope'] not in ('summary', 'transcript', 'both') or type(params['timestamps']) is not bool:
                raise DomainError('invalid_export', '导出选项无效。')
        elif kind != 'delete' or set(params) != {'meetingId'}:
            raise DomainError('invalid_operation', '操作无效。')
        if kind != 'search':
            self.repo.get(params['meetingId'])
        with self.lock:
            self.expire()
            if self.stopped or self.queue.full() or len(self.operations) >= 12:
                raise DomainError('library_busy', '资料操作繁忙，请稍后重试。')
            identifier = str(uuid.uuid4())
            self.operations[identifier] = {'state': 'queued', 'value': None, 'error': None, 'created': time.monotonic(), 'file': None}
            self.queue.put_nowait((identifier, kind, copy.deepcopy(params)))
            if self.thread is None:
                self.thread = threading.Thread(target=self.run, name='meeting-library', daemon=True)
                self.thread.start()
            return {'id': identifier}

    def expire(self):
        for identifier, item in list(self.operations.items()):
            if item['state'] not in ('queued', 'running') and time.monotonic() - item['created'] > 600:
                self.release(identifier)

    def release(self, identifier):
        with self.lock:
            item = self.operations.pop(identifier, None)
            if item and item['file']:
                item['file'].close()
        return {'released': True}

    def status(self, identifier):
        with self.lock:
            self.expire()
            item = self.operations.get(identifier)
            if not item:
                raise DomainError('operation_missing', '操作已取消或过期，请重试。')
            item['created'] = time.monotonic()
            return copy.deepcopy({key: item[key] for key in ('state', 'value', 'error')})

    def read(self, identifier, offset):
        if type(offset) is not int or not 0 <= offset <= 1_000_000_000:
            raise DomainError('invalid_params', '快照分页无效。')
        with self.lock:
            item = self.operations.get(identifier)
            if not item or item['state'] != 'completed' or not item['file']:
                raise DomainError('operation_missing', '导出快照已过期，请重试。')
            item['created'] = time.monotonic()
            item['file'].seek(offset)
            data = item['file'].read(16_384)
            return {'data': base64.b64encode(data).decode(), 'nextOffset': offset + len(data), 'done': offset + len(data) >= item['value']['bytes']}

    def export(self, params, cancelled=lambda: False):
        # SQLite backup makes an immutable copy in bounded steps without a long source read transaction.
        with self.repo.lock, self.repo.connect() as source:
            self.repo.assert_available(source, params['meetingId'])
        with tempfile.TemporaryDirectory(prefix='paa-snapshot-') as directory, self.repo.connect() as source, closing(sqlite3.connect(Path(directory) / 'snapshot.sqlite3')) as snapshot:
            deadline = time.monotonic() + 10
            def progress(_status, _remaining, _total):
                if time.monotonic() > deadline or self.stopped or cancelled():
                    raise DomainError('snapshot_busy', '资料快照未完成，请稍后重试。')
            source.backup(snapshot, pages=128, sleep=0.02, progress=progress)
            snapshot.row_factory = sqlite3.Row
            output = tempfile.TemporaryFile(mode='w+b')
            try:
                for line in document_lines(snapshot, params['meetingId'], params):
                    if self.stopped or cancelled():
                        raise DomainError('operation_missing', '导出已取消。')
                    output.write((line + '\n').encode('utf-8'))
                    if output.tell() > 1_000_000_000:
                        raise DomainError('export_large', '资料超过单次导出上限，请缩小导出范围。')
                meeting = snapshot.execute('SELECT title,COALESCE(startedAt,createdAt) AS date FROM meetings WHERE id=?', (params['meetingId'],)).fetchone()
                return {'bytes': output.tell(), 'title': meeting['title'], 'date': meeting['date']}, output
            except Exception:
                output.close()
                raise

    def run(self):
        while True:
            try:
                task = self.queue.get(timeout=30)
            except queue.Empty:
                with self.lock:
                    self.expire()
                    if self.stopped:
                        return
                continue
            if task is None:
                return
            identifier, kind, params = task
            with self.lock:
                if identifier not in self.operations or self.stopped:
                    continue
                self.operations[identifier]['state'] = 'running'
            output = None
            try:
                if kind == 'search':
                    value = search(self.repo, params)
                elif kind == 'delete':
                    value = self.repo.delete(params['meetingId'])
                else:
                    value, output = self.export(params, lambda: identifier not in self.operations)
                with self.lock:
                    if identifier in self.operations:
                        self.operations[identifier].update(state='completed', value=value, file=output)
                        output = None
            except Exception as exc:
                with self.lock:
                    if identifier in self.operations:
                        self.operations[identifier].update(state='failed', error={'code': getattr(exc, 'code', 'storage_error'), 'message': str(exc) if isinstance(exc, DomainError) else '资料处理失败，请检查磁盘空间、权限后重试。'})
            finally:
                if output:
                    output.close()

    def shutdown(self):
        with self.lock:
            self.stopped = True
            for identifier in list(self.operations):
                self.release(identifier)
        try:
            self.queue.put_nowait(None)
        except queue.Full:
            pass
