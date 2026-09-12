"""Additive summary persistence; latest attempt never destroys the last success."""
from __future__ import annotations

import hashlib
import json
import uuid

from .repository import DomainError, now


def migrate(db):
    db.execute('''CREATE TABLE summary_attempts (meetingId TEXT NOT NULL REFERENCES meetings(id),
                  inputHash TEXT NOT NULL, PRIMARY KEY(meetingId,inputHash))''')
    db.execute('''CREATE TABLE summary_jobs (id TEXT PRIMARY KEY, meetingId TEXT NOT NULL REFERENCES meetings(id),
        inputHash TEXT NOT NULL, profileId TEXT NOT NULL, revision TEXT NOT NULL, trigger TEXT NOT NULL,
        state TEXT NOT NULL, createdAt TEXT NOT NULL, errorCode TEXT, error TEXT)''')
    db.execute("CREATE UNIQUE INDEX summary_active ON summary_jobs(meetingId) WHERE state IN ('queued','running')")
    db.execute('''CREATE TABLE meeting_summaries (meetingId TEXT PRIMARY KEY REFERENCES meetings(id),
        taskId TEXT NOT NULL, inputHash TEXT NOT NULL, generatedAt TEXT NOT NULL, profileId TEXT NOT NULL,
        serviceName TEXT NOT NULL, model TEXT NOT NULL, parameters TEXT NOT NULL, sourceIncomplete INTEGER NOT NULL,
        content TEXT NOT NULL)''')


class SummaryStore:
    def __init__(self, repo):
        self.repo = repo
        self.interrupt_all()

    def snapshot(self, meeting_id):
        with self.repo.lock, self.repo.connect() as db:
            self.repo.assert_available(db, meeting_id)
            meeting = db.execute('SELECT status FROM meetings WHERE id=?', (meeting_id,)).fetchone()
            job = db.execute('SELECT state FROM transcription_jobs WHERE meetingId=?', (meeting_id,)).fetchone()
            if not meeting:
                raise DomainError('meeting_missing', '未找到这场会议。')
            if meeting[0] not in ('completed', 'interrupted') or not job or job[0] != 'completed':
                raise DomainError('transcript_incomplete', '请先完成这场会议的转写。')
            segments = [dict(row) for row in db.execute('SELECT id,startMs,endMs,text FROM transcript_segments WHERE meetingId=? ORDER BY sequence', (meeting_id,))]
        source = {'sourceIncomplete': meeting[0] == 'interrupted', 'segments': segments}
        encoded = json.dumps(source, ensure_ascii=False, sort_keys=True).encode()
        source['inputHash'] = hashlib.sha256(encoded).hexdigest()
        return source

    def register(self, meeting_id, snapshot, settings, automatic):
        with self.repo.lock, self.repo.connect() as db:
            self.repo.assert_available(db, meeting_id)
            if automatic:
                inserted = db.execute('INSERT OR IGNORE INTO summary_attempts VALUES (?,?)', (meeting_id, snapshot['inputHash'])).rowcount
                if not inserted:
                    return None
            row = db.execute("SELECT id FROM summary_jobs WHERE meetingId=? AND state IN ('queued','running')", (meeting_id,)).fetchone()
            if row:
                return None
            if not settings or not snapshot['segments']:
                return None
            task = str(uuid.uuid4())
            db.execute('INSERT INTO summary_jobs VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (task, meeting_id, snapshot['inputHash'], settings['profileId'], settings['revision'],
                        'auto' if automatic else 'manual', 'queued', now(), None, None))
            return task

    def claim(self, task):
        with self.repo.lock, self.repo.connect() as db:
            return db.execute("UPDATE summary_jobs SET state='running' WHERE id=? AND state='queued' AND meetingId NOT IN (SELECT meetingId FROM meeting_deletions)", (task,)).rowcount == 1

    def fail(self, task, code, message):
        with self.repo.lock, self.repo.connect() as db:
            db.execute("UPDATE summary_jobs SET state='failed',errorCode=?,error=? WHERE id=? AND state IN ('queued','running')", (code, message, task))

    def complete(self, task, snapshot, settings, content):
        with self.repo.lock, self.repo.connect() as db:
            job = db.execute("SELECT * FROM summary_jobs WHERE id=? AND state='running'", (task,)).fetchone()
            if not job or db.execute('SELECT 1 FROM meeting_deletions WHERE meetingId=?', (job['meetingId'],)).fetchone():
                return
            db.execute('''INSERT INTO meeting_summaries VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(meetingId) DO UPDATE SET
                taskId=excluded.taskId,inputHash=excluded.inputHash,generatedAt=excluded.generatedAt,profileId=excluded.profileId,
                serviceName=excluded.serviceName,model=excluded.model,parameters=excluded.parameters,
                sourceIncomplete=excluded.sourceIncomplete,content=excluded.content''',
                (job['meetingId'], task, snapshot['inputHash'], now(), settings['profileId'], settings['name'], settings['model'],
                 json.dumps(settings['parameters']), int(snapshot['sourceIncomplete']), json.dumps(content, ensure_ascii=False)))
            db.execute("UPDATE summary_jobs SET state='completed' WHERE id=?", (task,))

    def interrupt_all(self):
        with self.repo.lock, self.repo.connect() as db:
            db.execute("UPDATE summary_jobs SET state='interrupted',error='生成已中断，可手动重试。' WHERE state IN ('queued','running')")

    def cancel_queued(self, profile_id=None, revision=None, automatic_only=False):
        with self.repo.lock, self.repo.connect() as db:
            query = "UPDATE summary_jobs SET state='interrupted',error='设置已变更，请使用当前设置手动生成。' WHERE state='queued'"
            args = []
            if automatic_only:
                query += " AND trigger='auto'"
            elif profile_id:
                query += ' AND (profileId<>? OR revision<>?)'
                args = [profile_id, revision]
            db.execute(query, args)

    def get(self, meeting_id):
        self.repo.get(meeting_id)
        with self.repo.lock, self.repo.connect() as db:
            self.repo.assert_available(db, meeting_id)
            job = db.execute('SELECT * FROM summary_jobs WHERE meetingId=? ORDER BY rowid DESC LIMIT 1', (meeting_id,)).fetchone()
            result = db.execute('SELECT * FROM meeting_summaries WHERE meetingId=?', (meeting_id,)).fetchone()
        result = dict(result) if result else None
        if result:
            result['content'] = json.loads(result['content'])
            result['parameters'] = json.loads(result['parameters'])
            result['sourceIncomplete'] = bool(result['sourceIncomplete'])
        return {'task': dict(job) if job else None, 'result': result}
