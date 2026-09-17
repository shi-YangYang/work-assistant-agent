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


def migrate_speaker_minutes(db):
    for table in ('summary_jobs', 'meeting_summaries'):
        columns = {row[1] for row in db.execute(f'PRAGMA table_info({table})')}
        for name, definition in (('inputMode', "TEXT NOT NULL DEFAULT 'text'"),
                                 ('speakerIncomplete', 'INTEGER NOT NULL DEFAULT 0'),
                                 ('publication', 'TEXT'), ('inputSnapshot', 'TEXT')):
            if name not in columns:
                db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
    db.execute('DROP INDEX IF EXISTS summary_active')
    db.execute("CREATE UNIQUE INDEX summary_active ON summary_jobs(meetingId) WHERE state IN ('waiting_speakers','queued','running')")
    # Existing automatic attempts remain consumed when upgrading an old publication.
    db.execute("INSERT OR IGNORE INTO summary_attempts SELECT DISTINCT a.meetingId,'publication:' || COALESCE(p.generation,'legacy') FROM summary_attempts a LEFT JOIN transcript_publications p ON p.meetingId=a.meetingId")


def input_snapshot(db, meeting_id, input_mode='speakers'):
    if input_mode not in ('speakers', 'text'):
        raise DomainError('invalid_params', '纪要输入模式无效。')
    meeting = db.execute('SELECT status FROM meetings WHERE id=?', (meeting_id,)).fetchone()
    if not meeting:
        raise DomainError('meeting_missing', '未找到这场会议。')
    publication = db.execute('SELECT generation FROM transcript_publications WHERE meetingId=?', (meeting_id,)).fetchone()
    segments = [dict(row) for row in db.execute('SELECT id,startMs,endMs,text FROM transcript_segments WHERE meetingId=? ORDER BY sequence', (meeting_id,))]
    speaker_job = db.execute('SELECT state FROM speaker_jobs WHERE meetingId=?', (meeting_id,)).fetchone()
    if input_mode == 'speakers':
        speakers = {row['segmentId']: row for row in db.execute(
            "SELECT a.segmentId,a.manual AS assigned,s.id,s.name,s.manual,s.memberId FROM speaker_annotations a JOIN meeting_speakers s ON s.meetingId=a.meetingId AND s.id=a.speakerId WHERE a.meetingId=?", (meeting_id,))}
        for segment in segments:
            speaker = speakers.get(segment['id'])
            segment['speaker'] = {'id': speaker['id'], 'name': speaker['name'],
                'identitySource': 'manual' if speaker['manual'] else 'voiceprint' if speaker['memberId'] else 'anonymous',
                'assignmentSource': 'manual' if speaker['assigned'] else 'automatic'} if speaker else None
    source = {'sourceIncomplete': meeting[0] == 'interrupted', 'segments': segments,
              'inputMode': input_mode, 'publication': publication[0] if publication else 'legacy'}
    # Completion status is metadata: changes in actual text or used identities invalidate content.
    source['inputHash'] = hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    source['speakerIncomplete'] = input_mode == 'speakers' and (not speaker_job or speaker_job[0] != 'completed' or
        any(not segment['speaker'] or segment['speaker']['identitySource'] == 'anonymous' for segment in segments))
    return source


def is_stale(db, meeting_id, result):
    publication = db.execute('SELECT summaryStale FROM transcript_publications WHERE meetingId=?', (meeting_id,)).fetchone()
    if result['publication'] is None:  # v1 results retain their original compatibility semantics.
        return bool(publication and publication[0])
    return result['inputHash'] != input_snapshot(db, meeting_id, result['inputMode'])['inputHash']


class SummaryStore:
    def __init__(self, repo):
        self.repo = repo
        self.interrupt_all()

    def snapshot(self, meeting_id, input_mode='speakers'):
        with self.repo.lock, self.repo.connect() as db:
            self.repo.assert_available(db, meeting_id)
            meeting = db.execute('SELECT status FROM meetings WHERE id=?', (meeting_id,)).fetchone()
            job = db.execute('SELECT state FROM transcription_jobs WHERE meetingId=?', (meeting_id,)).fetchone()
            if not meeting:
                raise DomainError('meeting_missing', '未找到这场会议。')
            if meeting[0] not in ('completed', 'interrupted') or not job or job[0] != 'completed':
                raise DomainError('transcript_incomplete', '请先完成这场会议的转写。')
            if db.execute('SELECT 1 FROM candidate_jobs WHERE meetingId=?', (meeting_id,)).fetchone():
                raise DomainError('transcription_busy', '请先完成或取消重新转写，再生成纪要。')
            return input_snapshot(db, meeting_id, input_mode)

    def speakers_pending(self, meeting_id):
        with self.repo.lock, self.repo.connect() as db:
            return bool(db.execute("SELECT 1 FROM speaker_jobs WHERE meetingId=? AND state IN ('queued','running')", (meeting_id,)).fetchone())

    def register(self, meeting_id, snapshot, settings, automatic, waiting=False):
        with self.repo.lock, self.repo.connect() as db:
            self.repo.assert_available(db, meeting_id)
            current = input_snapshot(db, meeting_id, snapshot['inputMode'])
            if db.execute('SELECT 1 FROM candidate_jobs WHERE meetingId=?', (meeting_id,)).fetchone() or snapshot['inputHash'] != current['inputHash']:
                raise DomainError('transcript_changed', '文字或说话人信息正在更新，请稍后重新生成纪要。')
            if automatic:
                inserted = db.execute('INSERT OR IGNORE INTO summary_attempts VALUES (?,?)', (meeting_id, 'publication:' + snapshot['publication'])).rowcount
                if not inserted:
                    return None
            row = db.execute("SELECT id FROM summary_jobs WHERE meetingId=? AND state IN ('waiting_speakers','queued','running')", (meeting_id,)).fetchone()
            if row or not settings or not snapshot['segments']:
                return None
            task = str(uuid.uuid4())
            db.execute('INSERT INTO summary_jobs (id,meetingId,inputHash,profileId,revision,trigger,state,createdAt,errorCode,error,inputMode,speakerIncomplete,publication,inputSnapshot) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (task, meeting_id, snapshot['inputHash'], settings['profileId'], settings['revision'],
                        'auto' if automatic else 'manual', 'waiting_speakers' if waiting else 'queued', now(), None, None,
                        snapshot['inputMode'], int(snapshot['speakerIncomplete']), snapshot['publication'], json.dumps(snapshot, ensure_ascii=False)))
            return task

    def release_waiting(self, task, snapshot):
        with self.repo.lock, self.repo.connect() as db:
            return db.execute("UPDATE summary_jobs SET state='queued',inputHash=?,speakerIncomplete=?,inputSnapshot=? WHERE id=? AND state='waiting_speakers' AND publication=?",
                (snapshot['inputHash'], int(snapshot['speakerIncomplete']), json.dumps(snapshot, ensure_ascii=False), task, snapshot['publication'])).rowcount == 1

    def active_wait(self, task):
        with self.repo.lock, self.repo.connect() as db:
            return bool(db.execute("SELECT 1 FROM summary_jobs WHERE id=? AND state='waiting_speakers'", (task,)).fetchone())

    def claim(self, task):
        with self.repo.lock, self.repo.connect() as db:
            return db.execute("UPDATE summary_jobs SET state='running' WHERE id=? AND state='queued' AND meetingId NOT IN (SELECT meetingId FROM meeting_deletions)", (task,)).rowcount == 1

    def fail(self, task, code, message):
        with self.repo.lock, self.repo.connect() as db:
            db.execute("UPDATE summary_jobs SET state='failed',errorCode=?,error=? WHERE id=? AND state IN ('waiting_speakers','queued','running')", (code, message, task))

    def complete(self, task, snapshot, settings, content):
        with self.repo.lock, self.repo.connect() as db:
            job = db.execute("SELECT * FROM summary_jobs WHERE id=? AND state='running'", (task,)).fetchone()
            if not job or db.execute('SELECT 1 FROM meeting_deletions WHERE meetingId=?', (job['meetingId'],)).fetchone():
                return
            db.execute('''INSERT INTO meeting_summaries (meetingId,taskId,inputHash,generatedAt,profileId,serviceName,model,parameters,sourceIncomplete,content,inputMode,speakerIncomplete,publication,inputSnapshot)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(meetingId) DO UPDATE SET
                taskId=excluded.taskId,inputHash=excluded.inputHash,generatedAt=excluded.generatedAt,profileId=excluded.profileId,
                serviceName=excluded.serviceName,model=excluded.model,parameters=excluded.parameters,
                sourceIncomplete=excluded.sourceIncomplete,content=excluded.content,inputMode=excluded.inputMode,
                speakerIncomplete=excluded.speakerIncomplete,publication=excluded.publication,inputSnapshot=excluded.inputSnapshot''',
                (job['meetingId'], task, snapshot['inputHash'], now(), settings['profileId'], settings['name'], settings['model'],
                 json.dumps(settings['parameters']), int(snapshot['sourceIncomplete']), json.dumps(content, ensure_ascii=False),
                 snapshot['inputMode'], int(snapshot['speakerIncomplete']), snapshot['publication'], json.dumps(snapshot, ensure_ascii=False)))
            db.execute("UPDATE summary_jobs SET state='completed' WHERE id=?", (task,))
            stale = snapshot['inputHash'] != input_snapshot(db, job['meetingId'], snapshot['inputMode'])['inputHash']
            db.execute('UPDATE transcript_publications SET summaryStale=? WHERE meetingId=?', (int(stale), job['meetingId']))

    def interrupt_all(self):
        with self.repo.lock, self.repo.connect() as db:
            db.execute("UPDATE summary_jobs SET state='interrupted',error='生成已中断，可手动重试。' WHERE state IN ('waiting_speakers','queued','running')")

    def cancel_queued(self, profile_id=None, revision=None, automatic_only=False):
        with self.repo.lock, self.repo.connect() as db:
            query = "UPDATE summary_jobs SET state='interrupted',error='设置已变更，请使用当前设置手动生成。' WHERE state IN ('waiting_speakers','queued')"
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
                result.pop('inputSnapshot', None)
                result['stale'] = is_stale(db, meeting_id, result)
            job = dict(job) if job else None
            if job:
                job.pop('inputSnapshot', None)
                job['speakerIncomplete'] = bool(job['speakerIncomplete'])
                job['stale'] = is_stale(db, meeting_id, job)
        if result:
            result['content'] = json.loads(result['content'])
            result['parameters'] = json.loads(result['parameters'])
            result['sourceIncomplete'] = bool(result['sourceIncomplete'])
            result['speakerIncomplete'] = bool(result['speakerIncomplete'])
        return {'task': job, 'result': result}

    def source(self, meeting_id, segment_id):
        with self.repo.lock, self.repo.connect() as db:
            self.repo.assert_available(db, meeting_id)
            saved = db.execute('SELECT inputSnapshot FROM meeting_summaries WHERE meetingId=?', (meeting_id,)).fetchone()
            if saved and saved[0]:
                row = next((item for item in json.loads(saved[0])['segments'] if item['id'] == segment_id), None)
            else:
                row = db.execute('SELECT id,startMs,endMs,text FROM transcript_segments WHERE meetingId=? AND id=?', (meeting_id, segment_id)).fetchone()
            if not row:
                raise DomainError('source_missing', '未找到本次纪要的原文片段。')
            return {key: row[key] for key in ('id', 'startMs', 'endMs', 'text')}
