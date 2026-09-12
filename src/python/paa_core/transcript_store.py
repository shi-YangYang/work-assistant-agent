"""Transactional transcription checkpoints. Audio remains owned by the recording store."""
from __future__ import annotations

import json
import uuid

from .repository import ACTIVE, DomainError

JOB_ACTIVE = ('queued', 'running', 'draining')


def migrate(db):
    db.execute('''CREATE TABLE transcription_jobs (
        meetingId TEXT PRIMARY KEY REFERENCES meetings(id), state TEXT NOT NULL,
        modelId TEXT NOT NULL, revision TEXT NOT NULL, config TEXT NOT NULL,
        processedFrames INTEGER NOT NULL DEFAULT 0, targetFrames INTEGER,
        nextChunk INTEGER NOT NULL DEFAULT 0, error TEXT)''')
    db.execute('''CREATE TABLE audio_chunks (
        id TEXT PRIMARY KEY, meetingId TEXT NOT NULL REFERENCES transcription_jobs(meetingId),
        sequence INTEGER NOT NULL, startFrame INTEGER NOT NULL, endFrame INTEGER NOT NULL,
        contextStart INTEGER NOT NULL, contextEnd INTEGER NOT NULL,
        UNIQUE(meetingId,sequence), UNIQUE(meetingId,startFrame))''')
    db.execute('''CREATE TABLE transcript_segments (
        id TEXT PRIMARY KEY, meetingId TEXT NOT NULL REFERENCES transcription_jobs(meetingId),
        chunkId TEXT NOT NULL REFERENCES audio_chunks(id), sequence INTEGER NOT NULL,
        startMs INTEGER NOT NULL, endMs INTEGER NOT NULL, text TEXT NOT NULL,
        speaker TEXT, confidence REAL, UNIQUE(meetingId,sequence))''')
    db.execute('CREATE INDEX transcript_page ON transcript_segments(meetingId,sequence)')


class TranscriptStore:
    def __init__(self, repository):
        self.repo = repository
        self.on_completed = None
        # Recording recovery has already completed. No heavy work restarts implicitly.
        with self.repo.lock, self.repo.connect() as db:
            db.execute("UPDATE transcription_jobs SET state='paused' WHERE state IN ('queued','running','draining')")

    def job(self, meeting_id):
        self.repo.get(meeting_id)
        with self.repo.lock, self.repo.connect() as db:
            self.repo.assert_available(db, meeting_id)
            row = db.execute('SELECT * FROM transcription_jobs WHERE meetingId=?', (meeting_id,)).fetchone()
        if row:
            result = dict(row)
            result['config'] = json.loads(result['config'])
            return result
        return None

    def start(self, meeting_id, model_id, revision, config):
        meeting = self.repo.get(meeting_id)
        if meeting['status'] not in ACTIVE and not meeting['audioAvailable']:
            raise DomainError('audio_unavailable', meeting['audioError'] or '没有可转写的录音。')
        with self.repo.lock, self.repo.connect() as db:
            self.repo.assert_available(db, meeting_id)
            db.execute('''INSERT OR IGNORE INTO transcription_jobs
                (meetingId,state,modelId,revision,config) VALUES (?,?,?,?,?)''',
                (meeting_id, 'queued', model_id, revision, json.dumps(config)))
            db.execute("UPDATE transcription_jobs SET state='queued',error=NULL WHERE meetingId=? AND state IN ('paused','failed')", (meeting_id,))
        return self.job(meeting_id)

    def pending(self):
        with self.repo.lock, self.repo.connect() as db:
            return [row[0] for row in db.execute("SELECT meetingId FROM transcription_jobs WHERE state IN ('queued','running','draining') ORDER BY rowid")]

    def state(self, meeting_id, state, error=None, target=None):
        with self.repo.lock, self.repo.connect() as db:
            if not db.execute('SELECT 1 FROM meetings WHERE id=?', (meeting_id,)).fetchone() or db.execute('SELECT 1 FROM meeting_deletions WHERE meetingId=?', (meeting_id,)).fetchone():
                return False
            db.execute('UPDATE transcription_jobs SET state=?,error=?,targetFrames=COALESCE(?,targetFrames) WHERE meetingId=?',
                       (state, error, target, meeting_id))

        if state == 'completed' and self.on_completed:
            self.on_completed(meeting_id)

    def pause(self):
        with self.repo.lock, self.repo.connect() as db:
            db.execute("UPDATE transcription_jobs SET state='paused' WHERE state IN ('queued','running','draining')")

    def commit(self, job, chunk, segments, target=None):
        meeting_id = job['meetingId']
        chunk_id = str(uuid.uuid5(uuid.UUID(meeting_id), f"chunk:{job['nextChunk']}"))
        with self.repo.lock, self.repo.connect() as db:
            current = db.execute('SELECT * FROM transcription_jobs WHERE meetingId=?', (meeting_id,)).fetchone()
            if not current or db.execute('SELECT 1 FROM meeting_deletions WHERE meetingId=?', (meeting_id,)).fetchone():
                return False
            if current['processedFrames'] != chunk['startFrame'] or current['state'] not in JOB_ACTIVE:
                return False
            db.execute('INSERT INTO audio_chunks VALUES (?,?,?,?,?,?,?)',
                       (chunk_id, meeting_id, job['nextChunk'], chunk['startFrame'], chunk['endFrame'], chunk['contextStart'], chunk['contextEnd']))
            # IDs are stable across retries and order is bounded by each chunk's output cap.
            for index, segment in enumerate(segments):
                sequence = job['nextChunk'] * 1000 + index
                db.execute('INSERT INTO transcript_segments VALUES (?,?,?,?,?,?,?,?,?)',
                           (str(uuid.uuid5(uuid.UUID(meeting_id), f'segment:{sequence}')), meeting_id,
                            chunk_id, sequence, segment['startMs'], segment['endMs'], segment['text'], None, None))
            state = 'completed' if target is not None and chunk['endFrame'] == target else ('draining' if target is not None else 'running')
            db.execute('''UPDATE transcription_jobs SET processedFrames=?,nextChunk=nextChunk+1,
                state=?,targetFrames=?,error=NULL WHERE meetingId=?''',
                (chunk['endFrame'], state, target, meeting_id))
        if state == 'completed' and self.on_completed:
            self.on_completed(meeting_id)
        return True

    def page(self, meeting_id, cursor=-1):
        self.repo.get(meeting_id)
        with self.repo.lock, self.repo.connect() as db:
            self.repo.assert_available(db, meeting_id)
            rows = db.execute('''SELECT * FROM transcript_segments WHERE meetingId=? AND sequence>?
                ORDER BY sequence LIMIT 51''', (meeting_id, cursor)).fetchall()
        values = [dict(row) for row in rows[:50]]
        return {'segments': values, 'nextCursor': values[-1]['sequence'] if values else cursor, 'hasMore': len(rows) > 50}
