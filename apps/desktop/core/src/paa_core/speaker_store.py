"""Meeting-local speaker annotations; transcription text and citation IDs stay intact."""
from collections import defaultdict
import re

from .repository import ACTIVE, DomainError
from .transcript_store import TranscriptStore

SPEAKER_ID = re.compile(r'^speaker_[0-9]{1,3}$')


def migrate(db):
    db.execute('''CREATE TABLE IF NOT EXISTS speaker_jobs (
        meetingId TEXT PRIMARY KEY REFERENCES meetings(id), generation TEXT NOT NULL,
        state TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
        device TEXT, error TEXT)''')
    db.execute('''CREATE TABLE IF NOT EXISTS meeting_speakers (
        meetingId TEXT NOT NULL REFERENCES meetings(id), id TEXT NOT NULL,
        name TEXT NOT NULL, PRIMARY KEY(meetingId,id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS speaker_annotations (
        meetingId TEXT NOT NULL REFERENCES meetings(id), segmentId TEXT NOT NULL,
        speakerId TEXT, PRIMARY KEY(meetingId,segmentId))''')


def invalidate(db, meeting_id):
    for table in ('speaker_annotations', 'meeting_speakers', 'speaker_jobs'):
        db.execute(f'DELETE FROM {table} WHERE meetingId=?', (meeting_id,))


def assign_speaker(start, end, turns):
    """Keep ambiguous/overlapping utterances unassigned, never infer a real identity."""
    coverage = defaultdict(float)
    for left, right, speaker in turns:
        overlap = min(end, right) - max(start, left)
        if overlap > 0:
            coverage[speaker] += overlap
    ordered = sorted(coverage.items(), key=lambda item: -item[1])
    if not ordered:
        return None
    speaker, amount = ordered[0]
    total = sum(coverage.values())
    if amount < max(1, end - start) * .5 or amount / total < .85:
        return None
    return speaker


class SpeakerStore:
    def __init__(self, repo):
        self.repo = repo
        with repo.lock, repo.connect() as db:
            db.execute("UPDATE speaker_jobs SET state='paused',error=NULL WHERE state IN ('queued','running')")

    def status(self, meeting_id):
        self.repo.get(meeting_id)
        with self.repo.lock, self.repo.connect() as db:
            self.repo.assert_available(db, meeting_id)
            row = db.execute('SELECT * FROM speaker_jobs WHERE meetingId=?', (meeting_id,)).fetchone()
            result = dict(row) if row else dict(meetingId=meeting_id, generation=TranscriptStore.publication(db, meeting_id), state='not_started', revision=0, device=None, error=None)
            result['speakers'] = [dict(item) for item in db.execute('SELECT id,name FROM meeting_speakers WHERE meetingId=? ORDER BY id', (meeting_id,))]
        return result

    def start(self, meeting_id):
        meeting = self.repo.get(meeting_id, internal=True)
        if meeting['status'] in ACTIVE or not meeting['audioAvailable']:
            raise DomainError('audio_unavailable', '请先结束会议并保存录音。')
        with self.repo.lock, self.repo.connect() as db:
            self.repo.assert_available(db, meeting_id)
            job = db.execute('SELECT state FROM transcription_jobs WHERE meetingId=?', (meeting_id,)).fetchone()
            if not job or job[0] != 'completed' or db.execute('SELECT 1 FROM candidate_jobs WHERE meetingId=?', (meeting_id,)).fetchone():
                raise DomainError('transcription_busy', '请在文字转写完成后区分说话人。')
            existing = db.execute('SELECT state FROM speaker_jobs WHERE meetingId=?', (meeting_id,)).fetchone()
            if existing and existing[0] == 'completed':
                raise DomainError('speakers_completed', '已完成说话人区分，可直接修改姓名或调整片段。')
            generation = TranscriptStore.publication(db, meeting_id)
            db.execute("INSERT INTO speaker_jobs (meetingId,generation,state) VALUES (?,?,'running') ON CONFLICT(meetingId) DO UPDATE SET state='running',error=NULL", (meeting_id, generation))
        return meeting, generation

    def finish(self, meeting_id, generation, turns, device):
        # Model labels are canonicalized in first-appearance order, not numeric cluster order.
        if len(turns) > 200_000:
            raise DomainError('speakers_limit', '说话片段过多，未修改原文字。')
        labels = {}
        normalized = []
        for start, end, label in sorted(turns):
            if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or not 0 <= start < end <= 86_400_000 or not isinstance(label, str):
                raise DomainError('speakers_output', '说话人结果无效，原文字已保留。')
            if label not in labels:
                labels[label] = f'speaker_{len(labels):02d}'
            normalized.append((start, end, labels[label]))
        if len(labels) > 100:
            raise DomainError('speakers_limit', '检测到的说话人数异常，未修改原文字。')
        with self.repo.lock, self.repo.connect() as db:
            self.repo.assert_available(db, meeting_id)
            row = db.execute('SELECT state,generation FROM speaker_jobs WHERE meetingId=?', (meeting_id,)).fetchone()
            if not row or row['state'] != 'running' or row['generation'] != generation or TranscriptStore.publication(db, meeting_id) != generation:
                return False
            db.execute('DELETE FROM speaker_annotations WHERE meetingId=?', (meeting_id,))
            db.execute('DELETE FROM meeting_speakers WHERE meetingId=?', (meeting_id,))
            for index, identifier in enumerate(labels.values()):
                suffix = chr(65 + index) if index < 26 else str(index + 1)
                db.execute('INSERT INTO meeting_speakers VALUES (?,?,?)', (meeting_id, identifier, f'说话人 {suffix}'))
            segments = db.execute('SELECT id,startMs,endMs FROM transcript_segments WHERE meetingId=? ORDER BY sequence', (meeting_id,)).fetchall()
            active, position = [], 0
            for segment in segments:
                active = [turn for turn in active if turn[1] > segment['startMs']]
                while position < len(normalized) and normalized[position][0] < segment['endMs']:
                    if normalized[position][1] > segment['startMs']:
                        active.append(normalized[position])
                    position += 1
                selected = assign_speaker(segment['startMs'], segment['endMs'], active)
                db.execute('INSERT INTO speaker_annotations VALUES (?,?,?)', (meeting_id, segment['id'], selected))
            db.execute("UPDATE speaker_jobs SET state='completed',device=?,revision=revision+1,error=NULL WHERE meetingId=?", (device, meeting_id))
        return True

    def stop(self, meeting_id, error=None):
        with self.repo.lock, self.repo.connect() as db:
            db.execute("UPDATE speaker_jobs SET state=?,error=? WHERE meetingId=? AND state='running'", ('failed' if error else 'paused', error, meeting_id))

    def edit(self, meeting_id, generation, revision, *, speaker_id=None, name=None, segment_id=None):
        with self.repo.lock, self.repo.connect() as db:
            self.repo.assert_available(db, meeting_id)
            job = db.execute('SELECT * FROM speaker_jobs WHERE meetingId=?', (meeting_id,)).fetchone()
            if not job or job['state'] != 'completed' or job['generation'] != generation or job['revision'] != revision:
                raise DomainError('speakers_changed', '说话人信息已更新，请重新打开后修改。')
            if speaker_id is not None and (not isinstance(speaker_id, str) or not SPEAKER_ID.fullmatch(speaker_id) or not db.execute('SELECT 1 FROM meeting_speakers WHERE meetingId=? AND id=?', (meeting_id, speaker_id)).fetchone()):
                raise DomainError('invalid_speaker', '未找到这场会议中的说话人。')
            if name is not None:
                if speaker_id is None or not isinstance(name, str) or not 1 <= len(name.strip()) <= 40 or any(ord(c) < 32 or 127 <= ord(c) < 160 or c in '\u2028\u2029' for c in name):
                    raise DomainError('invalid_name', '姓名须为 1～40 个字符，不能包含换行。')
                db.execute('UPDATE meeting_speakers SET name=? WHERE meetingId=? AND id=?', (name.strip(), meeting_id, speaker_id))
            else:
                if not isinstance(segment_id, str) or not db.execute('SELECT 1 FROM transcript_segments WHERE meetingId=? AND id=?', (meeting_id, segment_id)).fetchone():
                    raise DomainError('invalid_segment', '未找到这段文字。')
                db.execute('INSERT INTO speaker_annotations VALUES (?,?,?) ON CONFLICT(meetingId,segmentId) DO UPDATE SET speakerId=excluded.speakerId', (meeting_id, segment_id, speaker_id))
            db.execute('UPDATE speaker_jobs SET revision=revision+1 WHERE meetingId=?', (meeting_id,))
        return self.status(meeting_id)
