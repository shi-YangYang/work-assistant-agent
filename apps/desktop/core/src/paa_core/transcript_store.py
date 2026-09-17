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


def migrate_library(db):
    db.execute("CREATE TABLE IF NOT EXISTS transcript_publications (meetingId TEXT PRIMARY KEY REFERENCES meetings(id), generation TEXT NOT NULL, summaryStale INTEGER NOT NULL DEFAULT 0)")
    db.execute("CREATE TABLE IF NOT EXISTS candidate_jobs (meetingId TEXT PRIMARY KEY REFERENCES meetings(id), state TEXT NOT NULL, modelId TEXT NOT NULL, revision TEXT NOT NULL, config TEXT NOT NULL, processedFrames INTEGER NOT NULL DEFAULT 0, targetFrames INTEGER, nextChunk INTEGER NOT NULL DEFAULT 0, error TEXT, generation TEXT NOT NULL, sourceFrames INTEGER NOT NULL, sourceAudioPath TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS candidate_chunks (id TEXT PRIMARY KEY, meetingId TEXT NOT NULL REFERENCES candidate_jobs(meetingId), sequence INTEGER NOT NULL, startFrame INTEGER NOT NULL, endFrame INTEGER NOT NULL, contextStart INTEGER NOT NULL, contextEnd INTEGER NOT NULL, UNIQUE(meetingId,sequence), UNIQUE(meetingId,startFrame))")
    db.execute("CREATE TABLE IF NOT EXISTS candidate_segments (id TEXT PRIMARY KEY, meetingId TEXT NOT NULL REFERENCES candidate_jobs(meetingId), chunkId TEXT NOT NULL REFERENCES candidate_chunks(id), sequence INTEGER NOT NULL, startMs INTEGER NOT NULL, endMs INTEGER NOT NULL, text TEXT NOT NULL, speaker TEXT, confidence REAL, UNIQUE(meetingId,sequence))")


class TranscriptStore:
    def __init__(self, repository):
        self.repo = repository
        self.on_completed = None
        with self.repo.lock, self.repo.connect() as db:
            for table in ('transcription_jobs', 'candidate_jobs'):
                db.execute(f"UPDATE {table} SET state='paused' WHERE state IN ('queued','running','draining')")

    @staticmethod
    def publication(db, meeting_id):
        row = db.execute('SELECT generation FROM transcript_publications WHERE meetingId=?', (meeting_id,)).fetchone()
        return row[0] if row else 'legacy'

    def _job(self, db, meeting_id, published=False):
        row = None if published else db.execute('SELECT * FROM candidate_jobs WHERE meetingId=?', (meeting_id,)).fetchone()
        candidate = row is not None
        row = row or db.execute('SELECT * FROM transcription_jobs WHERE meetingId=?', (meeting_id,)).fetchone()
        if row:
            result = dict(row)
            result['config'] = json.loads(result['config'])
            result['candidate'] = candidate
            result['generation'] = result.get('generation', self.publication(db, meeting_id))
            return result
        return None

    def job(self, meeting_id, published=False):
        self.repo.get(meeting_id)
        with self.repo.lock, self.repo.connect() as db:
            self.repo.assert_available(db, meeting_id)
            return self._job(db, meeting_id, published)

    def start(self, meeting_id, model_id, revision, config):
        meeting = self.repo.get(meeting_id)
        if meeting['status'] not in ACTIVE and not meeting['audioAvailable']:
            raise DomainError('audio_unavailable', meeting['audioError'] or '没有可转写的录音。')
        with self.repo.lock, self.repo.connect() as db:
            self.repo.assert_available(db, meeting_id)
            current = self._job(db, meeting_id)
            table = 'candidate_jobs' if current and current['candidate'] else 'transcription_jobs'
            if not current:
                db.execute("INSERT INTO transcription_jobs (meetingId,state,modelId,revision,config) VALUES (?,?,?,?,?)", (meeting_id, 'queued', model_id, revision, json.dumps(config)))
            db.execute(f"UPDATE {table} SET state='queued',error=NULL WHERE meetingId=? AND state IN ('paused','failed')", (meeting_id,))
        return self.job(meeting_id)

    def rerun(self, meeting_id, model_id, revision, config):
        meeting = self.repo.get(meeting_id, internal=True)
        if meeting['status'] not in ('completed', 'interrupted') or not meeting['audioAvailable']:
            raise DomainError('audio_unavailable', '会议结束且录音可用后才能重新转写。')
        with self.repo.lock, self.repo.connect() as db:
            self.repo.assert_available(db, meeting_id)
            current = self._job(db, meeting_id)
            if current and current['state'] in JOB_ACTIVE or db.execute("SELECT 1 FROM summary_jobs WHERE meetingId=? AND state IN ('queued','running')", (meeting_id,)).fetchone():
                raise DomainError('meeting_busy', '这场会议的转写或纪要正在处理，请完成后重试。')
            self._discard(db, meeting_id)
            generation = str(uuid.uuid4())
            db.execute("INSERT INTO candidate_jobs (meetingId,state,modelId,revision,config,generation,sourceFrames,sourceAudioPath) VALUES (?,?,?,?,?,?,?,?)", (meeting_id, 'queued', model_id, revision, json.dumps(config), generation, meeting['frames'], f"meetings/{meeting_id}/audio.wav" if not meeting.get('audioPath') else meeting['audioPath']))
        return self.job(meeting_id)

    @staticmethod
    def _discard(db, meeting_id):
        for table in ('candidate_segments', 'candidate_chunks', 'candidate_jobs'):
            db.execute(f'DELETE FROM {table} WHERE meetingId=?', (meeting_id,))

    def cancel_rerun(self, meeting_id):
        with self.repo.lock, self.repo.connect() as db:
            self.repo.assert_available(db, meeting_id)
            self._discard(db, meeting_id)

    def references(self, model_id, revision):
        with self.repo.lock, self.repo.connect() as db:
            return any(db.execute(f"SELECT 1 FROM {table} WHERE modelId=? AND revision=? AND state<>'completed' LIMIT 1", (model_id, revision)).fetchone() for table in ('transcription_jobs', 'candidate_jobs'))

    def pending(self):
        with self.repo.lock, self.repo.connect() as db:
            return [row[0] for row in db.execute("SELECT meetingId FROM candidate_jobs WHERE state IN ('queued','running','draining') UNION SELECT meetingId FROM transcription_jobs WHERE state IN ('queued','running','draining') AND meetingId NOT IN (SELECT meetingId FROM candidate_jobs)")]

    def _current(self, db, job):
        current = self._job(db, job['meetingId'])
        return current if current and current['generation'] == job.get('generation', 'legacy') and current['candidate'] == job.get('candidate', False) else None

    def _publish(self, db, job):
        meeting_id = job['meetingId']
        source = db.execute('SELECT frames,audioPath FROM meetings WHERE id=?', (meeting_id,)).fetchone()
        if not source or source['frames'] != job['sourceFrames'] or source['audioPath'] != job['sourceAudioPath']:
            raise DomainError('audio_changed', '录音来源已变化，本次结果未替换原文字。')
        from .speaker_store import invalidate
        invalidate(db, meeting_id)
        for table in ('transcript_segments', 'audio_chunks'):
            db.execute(f'DELETE FROM {table} WHERE meetingId=?', (meeting_id,))
        db.execute("INSERT INTO transcription_jobs (meetingId,state,modelId,revision,config,processedFrames,targetFrames,nextChunk,error) SELECT meetingId,state,modelId,revision,config,processedFrames,targetFrames,nextChunk,error FROM candidate_jobs WHERE meetingId=? ON CONFLICT(meetingId) DO UPDATE SET state=excluded.state, modelId=excluded.modelId, revision=excluded.revision, config=excluded.config, processedFrames=excluded.processedFrames, targetFrames=excluded.targetFrames, nextChunk=excluded.nextChunk, error=NULL", (meeting_id,))
        db.execute('INSERT INTO audio_chunks SELECT * FROM candidate_chunks WHERE meetingId=?', (meeting_id,))
        db.execute('INSERT INTO transcript_segments SELECT * FROM candidate_segments WHERE meetingId=?', (meeting_id,))
        db.execute('INSERT INTO transcript_publications VALUES (?,?,1) ON CONFLICT(meetingId) DO UPDATE SET generation=excluded.generation,summaryStale=1', (meeting_id, job['generation']))
        self._discard(db, meeting_id)

    def state(self, meeting_id, state, error=None, target=None, job=None):
        completed = False
        with self.repo.lock, self.repo.connect() as db:
            if not db.execute('SELECT 1 FROM meetings WHERE id=?', (meeting_id,)).fetchone() or db.execute('SELECT 1 FROM meeting_deletions WHERE meetingId=?', (meeting_id,)).fetchone():
                return False
            current = self._current(db, job) if job else self._job(db, meeting_id)
            if not current:
                return False
            table = 'candidate_jobs' if current['candidate'] else 'transcription_jobs'
            db.execute(f'UPDATE {table} SET state=?,error=?,targetFrames=COALESCE(?,targetFrames) WHERE meetingId=?', (state, error, target, meeting_id))
            if state == 'completed':
                if current['candidate']:
                    self._publish(db, current)
                else:
                    completed = True
        if completed and self.on_completed:
            self.on_completed(meeting_id)
        return True

    def pause(self):
        with self.repo.lock, self.repo.connect() as db:
            for table in ('transcription_jobs', 'candidate_jobs'):
                db.execute(f"UPDATE {table} SET state='paused' WHERE state IN ('queued','running','draining')")

    def commit(self, job, chunk, segments, target=None):
        meeting_id = job['meetingId']
        identity = '' if job.get('generation', 'legacy') == 'legacy' else job['generation'] + ':'
        chunk_id = str(uuid.uuid5(uuid.UUID(meeting_id), f"{identity}chunk:{job['nextChunk']}"))
        completed = False
        with self.repo.lock, self.repo.connect() as db:
            current = self._current(db, job)
            if not current or db.execute('SELECT 1 FROM meeting_deletions WHERE meetingId=?', (meeting_id,)).fetchone():
                return False
            if current['processedFrames'] != chunk['startFrame'] or current['state'] not in JOB_ACTIVE:
                return False
            jobs, chunks, texts = ('candidate_jobs', 'candidate_chunks', 'candidate_segments') if job['candidate'] else ('transcription_jobs', 'audio_chunks', 'transcript_segments')
            db.execute(f'INSERT INTO {chunks} VALUES (?,?,?,?,?,?,?)', (chunk_id, meeting_id, job['nextChunk'], chunk['startFrame'], chunk['endFrame'], chunk['contextStart'], chunk['contextEnd']))
            for index, segment in enumerate(segments):
                sequence = job['nextChunk'] * 1000 + index
                db.execute(f'INSERT INTO {texts} VALUES (?,?,?,?,?,?,?,?,?)', (str(uuid.uuid5(uuid.UUID(meeting_id), f'{identity}segment:{sequence}')), meeting_id, chunk_id, sequence, segment['startMs'], segment['endMs'], segment['text'], None, None))
            state = 'completed' if target is not None and chunk['endFrame'] == target else ('draining' if target is not None else 'running')
            db.execute(f"UPDATE {jobs} SET processedFrames=?,nextChunk=nextChunk+1,state=?,targetFrames=?,error=NULL WHERE meetingId=?", (chunk['endFrame'], state, target, meeting_id))
            if state == 'completed':
                if job['candidate']:
                    self._publish(db, job)
                else:
                    completed = True
        if completed and self.on_completed:
            self.on_completed(meeting_id)
        return True

    def page(self, meeting_id, cursor=-1, publication=None):
        self.repo.get(meeting_id)
        with self.repo.lock, self.repo.connect() as db:
            self.repo.assert_available(db, meeting_id)
            current = self.publication(db, meeting_id)
            if publication is not None and publication != current:
                raise DomainError('transcript_changed', '文字记录已更新，正在重新读取。')
            rows = db.execute('SELECT t.id,t.meetingId,t.chunkId,t.sequence,t.startMs,t.endMs,t.text,t.confidence,a.speakerId AS speaker, s.name AS speakerName FROM transcript_segments t LEFT JOIN speaker_annotations a ON a.meetingId=t.meetingId AND a.segmentId=t.id LEFT JOIN meeting_speakers s ON s.meetingId=a.meetingId AND s.id=a.speakerId WHERE t.meetingId=? AND t.sequence>? ORDER BY t.sequence LIMIT 51', (meeting_id, cursor)).fetchall()
        values = [dict(row) for row in rows[:50]]
        return {'segments': values, 'nextCursor': values[-1]['sequence'] if values else cursor, 'hasMore': len(rows) > 50, 'publication': current}
