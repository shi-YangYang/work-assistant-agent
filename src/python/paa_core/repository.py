"""Versioned SQLite metadata; audio paths are internal and rooted in user data."""
from __future__ import annotations

import re
import sqlite3
import threading
import time
import wave
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path

from .audio_store import inspect_audio, inspect_recoverable_audio, recover_audio

ID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
ACTIVE = ('starting', 'recording', 'pausing', 'paused', 'resuming', 'stopping')


class DomainError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def valid_id(value: object) -> bool:
    return isinstance(value, str) and bool(ID_PATTERN.fullmatch(value))


def now() -> str:
    return datetime.now().astimezone().isoformat()


class Repository:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.database = self.root / 'meetings.sqlite3'
        with self.connect() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if version not in (0, 1, 2, 3, 4, 5) or (version == 0 and tables):
                raise DomainError('storage_schema', '会议数据库版本不兼容，请保留数据并联系维护者。')
            if version in (1, 2, 3, 4):
                self.backup_schema(db, version)
            db.execute('BEGIN IMMEDIATE')
            if version == 0:
                db.execute('''CREATE TABLE meetings (
                    id TEXT PRIMARY KEY, operationId TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
                    createdAt TEXT NOT NULL, startedAt TEXT, endedAt TEXT, status TEXT NOT NULL,
                    durationMs INTEGER NOT NULL DEFAULT 0, errorCode TEXT, deviceName TEXT,
                    sampleRate INTEGER NOT NULL DEFAULT 48000, channels INTEGER NOT NULL DEFAULT 1,
                    sampleWidth INTEGER NOT NULL DEFAULT 2, frames INTEGER NOT NULL DEFAULT 0,
                    bytes INTEGER NOT NULL DEFAULT 0, audioPath TEXT)''')
            if version < 2:
                from .transcript_store import migrate
                migrate(db)
            if version < 3:
                from .summary_store import migrate as migrate_summary
                migrate_summary(db)
            if version < 4:
                # New persisted active states require newer recovery semantics.
                db.execute('PRAGMA user_version=4')
            if version < 5:
                db.execute('CREATE TABLE meeting_deletions (meetingId TEXT PRIMARY KEY REFERENCES meetings(id), error TEXT)')
                db.execute('PRAGMA user_version=5')
        self.recover_deletions()
        self.recover()

    def backup_schema(self, db, version):
        destination = self.root / f'meetings.schema{version}.backup.sqlite3'
        staging = self.root / f'meetings.schema{version}.backup.staging'
        if destination.is_symlink() or staging.is_symlink():
            raise DomainError('storage_backup', '迁移备份位置无效，请保留原数据库并检查存储。')
        busy_since = None
        def progress(status, _remaining, _total):
            nonlocal busy_since
            # Bound continuous lock waits, not successful copying or the final disk flush.
            if status not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                busy_since = None
                return
            current = time.monotonic()
            if busy_since is None:
                busy_since = current
            elif current - busy_since >= 2:
                raise DomainError('storage_busy', '数据库仍被占用，迁移未开始；关闭其他实例后重试。')
        try:
            with closing(sqlite3.connect(staging)) as backup:
                db.backup(backup, pages=128, progress=progress, sleep=0.02)
            staging.replace(destination)
        finally:
            staging.unlink(missing_ok=True)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=0.25)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def path(self, meeting_id: str, filename: str) -> Path:
        if not valid_id(meeting_id) or filename not in ('recording.wav', 'audio.wav', 'recovered.wav', 'recovered.recovering'):
            raise DomainError('invalid_id', '会议标识无效。')
        candidate = self.root / 'meetings' / meeting_id / filename
        if not candidate.resolve().is_relative_to(self.root) or any(p.is_symlink() for p in (candidate, candidate.parent, candidate.parent.parent)):
            raise DomainError('audio_path', '录音文件位置无效。')
        return candidate

    def create(self, meeting_id: str, operation_id: str) -> dict:
        timestamp = now()
        with self.lock, self.connect() as db:
            db.execute('INSERT INTO meetings (id,operationId,title,createdAt,status) VALUES (?,?,?,?,?)',
                       (meeting_id, operation_id, datetime.now().strftime('会议 %Y-%m-%d %H:%M'), timestamp, 'starting'))
        return self.get(meeting_id)

    def update(self, meeting_id: str, **fields) -> None:
        allowed = {'startedAt', 'endedAt', 'status', 'durationMs', 'errorCode', 'deviceName', 'sampleRate', 'frames', 'bytes', 'audioPath'}
        if not fields or set(fields) - allowed:
            raise ValueError('Invalid metadata fields')
        with self.lock, self.connect() as db:
            self.assert_available(db, meeting_id)
            db.execute('UPDATE meetings SET ' + ','.join(f'{key}=?' for key in fields) + ' WHERE id=?', (*fields.values(), meeting_id))

    def by_operation(self, operation_id: str):
        with self.lock, self.connect() as db:
            row = db.execute('SELECT * FROM meetings WHERE operationId=?', (operation_id,)).fetchone()
        return self.present(dict(row)) if row else None

    def get(self, meeting_id: str, internal=False) -> dict:
        if not valid_id(meeting_id):
            raise DomainError('invalid_id', '会议标识无效。')
        with self.lock, self.connect() as db:
            row = db.execute('SELECT m.*,d.meetingId IS NOT NULL AS deleting,d.error AS deletionError FROM meetings m LEFT JOIN meeting_deletions d ON d.meetingId=m.id WHERE m.id=?', (meeting_id,)).fetchone()
        if row is None:
            raise DomainError('meeting_missing', '未找到这场会议。')
        return self.present(dict(row), internal)

    def list(self, offset=0) -> dict:
        with self.lock, self.connect() as db:
            rows = db.execute('SELECT m.*,d.meetingId IS NOT NULL AS deleting,d.error AS deletionError FROM meetings m LEFT JOIN meeting_deletions d ON d.meetingId=m.id ORDER BY createdAt DESC, id DESC LIMIT 51 OFFSET ?', (offset,)).fetchall()
        return {'meetings': [self.present(dict(row)) for row in rows[:50]], 'hasMore': len(rows) > 50}

    def present(self, row: dict, internal=False) -> dict:
        row.pop('operationId', None)
        relative = row.pop('audioPath')
        row['deleting'] = bool(row.get('deleting', False))
        row['audioAvailable'] = False
        row['audioError'] = None
        if row['deleting']:
            row['audioError'] = '删除未完成，请重试删除。'
        elif relative and row['status'] == 'failed':
            row['audioError'] = '录音恢复暂未完成，请检查磁盘空间和目录权限后重新连接；原始文件已保留。'
        elif relative and row['status'] not in ACTIVE:
            try:
                expected = f"meetings/{row['id']}/{Path(relative).name}"
                if relative != expected:
                    raise ValueError('Invalid path')
                path = self.path(row['id'], Path(relative).name)
                info = inspect_audio(path, row['sampleRate'])
                if info['frames'] != row['frames']:
                    raise ValueError('Inconsistent frame count')
                row['audioAvailable'] = True
                if internal:
                    row['audioPath'] = relative
            except (OSError, ValueError, EOFError, wave.Error, DomainError):
                row['audioError'] = '录音文件缺失、损坏或无法读取，请保留数据并检查存储目录。'
        row['format'] = 'wav'
        return row

    def recover(self) -> None:
        with self.connect() as db:
            rows = db.execute("""SELECT * FROM meetings WHERE (status IN ('starting','recording','pausing','paused','resuming','stopping')
                              OR (status='failed' AND audioPath IS NOT NULL)) AND id NOT IN (SELECT meetingId FROM meeting_deletions)""").fetchall()
        for row in rows:
            info = None
            pending_info = None
            recovery_pending = False
            for filename in ('audio.wav', 'recording.wav', 'recovered.wav'):
                try:
                    source = self.path(row['id'], filename)
                    if not source.exists():
                        continue
                    pending_info = inspect_recoverable_audio(source, row['sampleRate'])
                    target = self.path(row['id'], 'recovered.wav')
                    info = inspect_audio(source, row['sampleRate']) if filename == 'recovered.wav' else recover_audio(source, target, row['sampleRate'])
                    break
                except OSError:
                    recovery_pending = True
                except (ValueError, EOFError, wave.Error, DomainError):
                    continue
            self.update(row['id'], status='interrupted' if info else 'failed', endedAt=row['endedAt'] or now(),
                        errorCode=row['errorCode'] or 'process_interrupted',
                        audioPath=f"meetings/{row['id']}/recovered.wav" if info or recovery_pending else None,
                        **(info or pending_info or {'frames': 0, 'bytes': 0, 'durationMs': 0}))

    def assert_available(self, db, meeting_id):
        if not db.execute('SELECT 1 FROM meetings WHERE id=?', (meeting_id,)).fetchone():
            raise DomainError('meeting_missing', '未找到这场会议。')
        if db.execute('SELECT 1 FROM meeting_deletions WHERE meetingId=?', (meeting_id,)).fetchone():
            raise DomainError('meeting_deleting', '这场会议删除尚未完成，请重试删除。')

    def rename(self, meeting_id, title):
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100 or any(ord(c) < 32 or 127 <= ord(c) < 160 or c in '\u2028\u2029' for c in title):
            raise DomainError('invalid_title', '名称须为 1～100 个字符，不能包含换行或控制字符。')
        with self.lock, self.connect() as db:
            self.assert_available(db, meeting_id)
            if db.execute('SELECT status FROM meetings WHERE id=?', (meeting_id,)).fetchone()[0] in ACTIVE:
                raise DomainError('meeting_busy', '请在会议结束并保存后改名。')
            db.execute('UPDATE meetings SET title=? WHERE id=?', (title.strip(), meeting_id))
        return self.get(meeting_id)

    def delete(self, meeting_id, recovery=False):
        if not valid_id(meeting_id):
            raise DomainError('invalid_id', '会议标识无效。')
        with self.lock, self.connect() as db:
            meeting = db.execute('SELECT status FROM meetings WHERE id=?', (meeting_id,)).fetchone()
            if not meeting:
                return {'deleted': True}
            if not recovery:
                busy = (meeting[0] in ACTIVE or db.execute("SELECT 1 FROM transcription_jobs WHERE meetingId=? AND state IN ('queued','running','draining')", (meeting_id,)).fetchone() or db.execute("SELECT 1 FROM summary_jobs WHERE meetingId=? AND state IN ('queued','running')", (meeting_id,)).fetchone())
                if busy:
                    raise DomainError('meeting_busy', '这场会议仍在录音、保存、转写或生成纪要，请完成后再删除。')
            db.execute('INSERT OR IGNORE INTO meeting_deletions VALUES (?,NULL)', (meeting_id,))
        try:
            # The durable intent prevents admission and late writes while file I/O runs without the repository lock.
            directory = self.path(meeting_id, 'audio.wav').parent
            if directory.exists():
                children = list(directory.iterdir())
                if any(p.name not in ('audio.wav', 'recording.wav', 'recovered.wav', 'recovered.recovering') or p.is_symlink() or not p.is_file() for p in children):
                    raise DomainError('audio_path', '会议目录存在无法安全删除的文件，请保留目录并检查。')
                for child in children:
                    self.path(meeting_id, child.name).unlink(missing_ok=True)
                directory.rmdir()
            with self.lock, self.connect() as db:
                for table in ('meeting_summaries', 'summary_jobs', 'summary_attempts', 'transcript_segments', 'audio_chunks', 'transcription_jobs', 'meeting_deletions'):
                    db.execute(f'DELETE FROM {table} WHERE meetingId=?', (meeting_id,))
                db.execute('DELETE FROM meetings WHERE id=?', (meeting_id,))
            return {'deleted': True}
        except (OSError, sqlite3.Error, DomainError):
            with self.lock, self.connect() as db:
                db.execute('UPDATE meeting_deletions SET error=? WHERE meetingId=?', ('删除未完成，请关闭占用录音的程序，检查目录权限后重试；重新启动也会继续清理。', meeting_id))
            raise DomainError('delete_failed', '删除未完成，请关闭占用录音的程序，检查目录权限后重试。') from None

    def recover_deletions(self):
        with self.connect() as db:
            identifiers = [row[0] for row in db.execute('SELECT meetingId FROM meeting_deletions')]
        for meeting_id in identifiers:
            try:
                self.delete(meeting_id, recovery=True)
            except DomainError:
                pass
