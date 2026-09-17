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


def migrate_voiceprints(db):
    additions = {'meeting_speakers': [('manual','INTEGER NOT NULL DEFAULT 0'),('memberId','TEXT')],
                 'speaker_annotations':[('manual','INTEGER NOT NULL DEFAULT 0')],
                 'speaker_jobs':[('processedMs','INTEGER NOT NULL DEFAULT 0'),('voiceprintScope','TEXT')]}
    for table, fields in additions.items():
        columns={row[1] for row in db.execute(f'PRAGMA table_info({table})')}
        for name,definition in fields:
            if name not in columns:
                db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
                if table=='speaker_annotations' and name=='manual':
                    # Old schema did not record manual assignments: preserve them all.
                    db.execute('UPDATE speaker_annotations SET manual=1')
    db.execute("UPDATE meeting_speakers SET manual=1 WHERE name NOT LIKE '说话人 %'")


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

    def begin_live(self, meeting_id, scope):
        with self.repo.lock, self.repo.connect() as db:
            self.repo.assert_available(db, meeting_id)
            generation = TranscriptStore.publication(db, meeting_id)
            row = db.execute('SELECT * FROM speaker_jobs WHERE meetingId=?', (meeting_id,)).fetchone()
            if row and row['state'] == 'completed':
                return None
            db.execute("INSERT INTO speaker_jobs (meetingId,generation,state,voiceprintScope) VALUES (?,?,'running',?) ON CONFLICT(meetingId) DO UPDATE SET state='running',error=NULL,voiceprintScope=excluded.voiceprintScope", (meeting_id,generation,scope))
            return generation

    def finish(self, meeting_id, generation, turns, device, identities=None):
        return self.publish(meeting_id,generation,turns,device,identities=identities,final=True)

    def publish(self, meeting_id, generation, turns, device, *, identities=None, final=False, start_ms=0, end_ms=None, aliases=None):
        if len(turns) > 200_000:
            raise DomainError('speakers_limit', '说话片段过多，未修改原文字。')
        identities, aliases = identities or {}, aliases or {}
        normalized = []
        for start,end,label in sorted(turns):
            if not isinstance(start,(float,int)) or not isinstance(end,(float,int)) or not 0 <= start < end <= 86_400_000 or not isinstance(label,str):
                raise DomainError('speakers_output', '说话人结果无效，原文字已保留。')
            normalized.append((start,end,label))
        labels = list(dict.fromkeys(turn[2] for turn in normalized))
        if len(labels)>100:
            raise DomainError('speakers_limit', '检测到的说话人数异常，未修改原文字。')
        with self.repo.lock, self.repo.connect() as db:
            self.repo.assert_available(db, meeting_id)
            row = db.execute('SELECT state,generation FROM speaker_jobs WHERE meetingId=?',(meeting_id,)).fetchone()
            if not row or row['state']!='running' or row['generation']!=generation or TranscriptStore.publication(db,meeting_id)!=generation:
                return False
            existing = {r['id']:dict(r) for r in db.execute('SELECT * FROM meeting_speakers WHERE meetingId=?',(meeting_id,))}
            segments = db.execute('SELECT t.id,t.startMs,t.endMs,a.speakerId,a.manual FROM transcript_segments t LEFT JOIN speaker_annotations a ON a.meetingId=t.meetingId AND a.segmentId=t.id WHERE t.meetingId=? ORDER BY t.sequence',(meeting_id,)).fetchall()
            votes_by_label = defaultdict(lambda: defaultdict(float))
            active, position = [], 0
            for left,right,label in normalized:
                active = [segment for segment in active if segment['endMs']>left]
                while position<len(segments) and segments[position]['startMs']<right:
                    if segments[position]['endMs']>left: active.append(segments[position])
                    position+=1
                for segment in active:
                    if segment['speakerId'] in existing:
                        votes_by_label[label][segment['speakerId']]+=max(0,min(right,segment['endMs'])-max(left,segment['startMs']))
            mapping, used = {}, set()
            for label in labels:
                identity = identities.get(label)
                selected = next((s['id'] for s in existing.values() if identity and s['memberId']==identity['memberId'] and s['id'] not in used),None)
                if not selected and aliases.get(label) in existing and aliases[label] not in used and (not identity or existing[aliases[label]]['memberId'] in (None,identity['memberId'])):
                    selected = aliases[label]
                if not selected:
                    votes = {key:value for key,value in votes_by_label[label].items()
                             if key not in used and value>=500 and
                             (not existing[key]['memberId'] or
                              (identity and existing[key]['memberId']==identity['memberId']) or
                              (not identity and aliases.get(label)==key))}
                    if votes: selected=max(votes,key=votes.get)
                if not selected:
                    index = 0
                    while f'speaker_{index:02d}' in existing: index+=1
                    if index>=100:
                        raise DomainError('speakers_limit','说话人数超限，原文字已保留。')
                    selected=f'speaker_{index:02d}'
                    name=f'说话人 {chr(65+index) if index<26 else index+1}'
                    db.execute('INSERT INTO meeting_speakers (meetingId,id,name) VALUES (?,?,?)',(meeting_id,selected,name))
                    existing[selected]={'id':selected,'name':name,'manual':0,'memberId':None}
                mapping[label]=selected; used.add(selected)
                if not existing[selected]['manual'] and (identity or final or not existing[selected]['memberId']):
                    index=int(selected.split('_')[1])
                    name = identity['name'] if identity else f'说话人 {chr(65+index) if index<26 else index+1}'
                    db.execute('UPDATE meeting_speakers SET name=?,memberId=? WHERE meetingId=? AND id=?',(name,identity['memberId'] if identity else None,meeting_id,selected))
            canonical = [(a,b,mapping[label]) for a,b,label in normalized]
            active, position = [], 0
            for segment in segments:
                active = [turn for turn in active if turn[1]>segment['startMs']]
                while position<len(canonical) and canonical[position][0]<segment['endMs']:
                    if canonical[position][1]>segment['startMs']: active.append(canonical[position])
                    position+=1
                if segment['manual'] or existing.get(segment['speakerId'],{}).get('manual'): continue
                if not final and (segment['endMs']<=start_ms or segment['startMs']>=(end_ms or 86_400_000)): continue
                selected=assign_speaker(segment['startMs'],segment['endMs'],active)
                if not final and selected is None and existing.get(segment['speakerId'],{}).get('memberId'):
                    continue
                db.execute('INSERT INTO speaker_annotations (meetingId,segmentId,speakerId) VALUES (?,?,?) ON CONFLICT(meetingId,segmentId) DO UPDATE SET speakerId=excluded.speakerId',(meeting_id,segment['id'],selected))
            db.execute("UPDATE speaker_jobs SET state=?,device=?,revision=revision+1,processedMs=MAX(processedMs,?),error=NULL WHERE meetingId=?",('completed' if final else 'running',device,int(end_ms or max((t[1] for t in normalized),default=0)),meeting_id))
            if final:
                db.execute('DELETE FROM meeting_speakers WHERE meetingId=? AND manual=0 AND NOT EXISTS (SELECT 1 FROM speaker_annotations a WHERE a.meetingId=meeting_speakers.meetingId AND a.speakerId=meeting_speakers.id)',(meeting_id,))
        return mapping if mapping else True

    def identify(self, meeting_id, generation, identities):
        with self.repo.lock, self.repo.connect() as db:
            job=db.execute('SELECT state,generation FROM speaker_jobs WHERE meetingId=?',(meeting_id,)).fetchone()
            if not job or job['state']!='running' or job['generation']!=generation or TranscriptStore.publication(db,meeting_id)!=generation:
                return False
            changed=0
            for speaker,identity in identities.items():
                changed+=db.execute('UPDATE meeting_speakers SET name=?,memberId=? WHERE meetingId=? AND id=? AND manual=0 AND (memberId IS NOT ? OR name!=?)',(identity['name'],identity['memberId'],meeting_id,speaker,identity['memberId'],identity['name'])).rowcount
            if changed:
                db.execute('UPDATE speaker_jobs SET revision=revision+1 WHERE meetingId=?',(meeting_id,))
            return True

    def stop(self, meeting_id, error=None):
        with self.repo.lock, self.repo.connect() as db:
            db.execute("UPDATE speaker_jobs SET state=?,error=? WHERE meetingId=? AND state='running'", ('failed' if error else 'paused', error, meeting_id))

    def edit(self, meeting_id, generation, revision, *, speaker_id=None, name=None, segment_id=None):
        with self.repo.lock, self.repo.connect() as db:
            self.repo.assert_available(db, meeting_id)
            job = db.execute('SELECT * FROM speaker_jobs WHERE meetingId=?', (meeting_id,)).fetchone()
            if not job or job['state'] not in ('completed', 'running', 'paused', 'failed') or job['generation'] != generation or job['revision'] != revision:
                raise DomainError('speakers_changed', '说话人信息已更新，请重新打开后修改。')
            if speaker_id is not None and (not isinstance(speaker_id, str) or not SPEAKER_ID.fullmatch(speaker_id) or not db.execute('SELECT 1 FROM meeting_speakers WHERE meetingId=? AND id=?', (meeting_id, speaker_id)).fetchone()):
                raise DomainError('invalid_speaker', '未找到这场会议中的说话人。')
            if name is not None:
                if speaker_id is None or not isinstance(name, str) or not 1 <= len(name.strip()) <= 100 or any(ord(c) < 32 or 127 <= ord(c) < 160 or c in '\u2028\u2029' for c in name):
                    raise DomainError('invalid_name', '姓名须为 1～100 个字符，不能包含换行。')
                db.execute('UPDATE meeting_speakers SET name=?,manual=1 WHERE meetingId=? AND id=?', (name.strip(), meeting_id, speaker_id))
            else:
                if not isinstance(segment_id, str) or not db.execute('SELECT 1 FROM transcript_segments WHERE meetingId=? AND id=?', (meeting_id, segment_id)).fetchone():
                    raise DomainError('invalid_segment', '未找到这段文字。')
                db.execute('INSERT INTO speaker_annotations (meetingId,segmentId,speakerId,manual) VALUES (?,?,?,1) ON CONFLICT(meetingId,segmentId) DO UPDATE SET speakerId=excluded.speakerId,manual=1', (meeting_id, segment_id, speaker_id))
            db.execute('UPDATE speaker_jobs SET revision=revision+1 WHERE meetingId=?', (meeting_id,))
        return self.status(meeting_id)
