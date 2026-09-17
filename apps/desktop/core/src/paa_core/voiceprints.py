"""Company templates stay in memory; bounded recognition never blocks recording."""
from __future__ import annotations

import tempfile
import threading
import wave
from pathlib import Path

from paa_voiceprints import MODEL_ID, VoiceprintError, match, validate_profiles
from .repository import ACTIVE, DomainError
from .speaker_worker import run_worker


class Voiceprints:
    def __init__(self, repo, recorder, transcription, speakers, runner=run_worker):
        self.repo, self.recorder, self.transcription, self.speakers = repo, recorder, transcription, speakers
        self.runner = runner
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.closed = threading.Event()
        self.cancelled = threading.Event()
        self.version = 0
        self.scope = None
        self.profiles = []
        self.meetings = set()
        self.tracks = {}
        self.inflight = None
        self.state, self.error = 'disabled', None
        self.thread = threading.Thread(target=self.run, name='voiceprint-scheduler', daemon=True)
        self.thread.start()

    def status(self):
        with self.lock:
            return {'enabled':bool(self.scope and self.profiles), 'profileCount':len(self.profiles),
                    'modelId':MODEL_ID,'state':self.state,'error':self.error}

    def configure(self, scope, model_id, profiles):
        if scope is not None and (not isinstance(scope,str) or not 1<=len(scope)<=512):
            raise DomainError('invalid_params','公司声纹作用域无效。')
        if scope is None and profiles:
            raise DomainError('invalid_params','声纹需要公司账号作用域。')
        try:
            clean = validate_profiles(model_id, profiles)
        except VoiceprintError as exc:
            raise DomainError(exc.code,str(exc)) from None
        with self.lock:
            previous_meetings = list(self.meetings)
            had_profiles = bool(self.profiles)
            self.cancelled.set()
            # Also invalidate post-meeting inference holding an old template snapshot.
            self.version += 1
            self.scope, self.profiles = scope, clean
            self.cancelled = threading.Event()
            self.meetings.clear(); self.tracks.clear()
            self.state, self.error = ('ready' if scope and clean else 'disabled'), None
        if had_profiles:
            self.speakers.pause()
        for meeting_id in previous_meetings:
            self.speakers.store.stop(meeting_id)
        current = self.recorder.status()
        if current.get('meetingId') and current['state'] in ACTIVE:
            self.watch(current['meetingId'])
        self.wake.set()
        return self.status()

    def snapshot(self):
        with self.lock:
            return self.version, self.scope, self.profiles

    def pending(self, meeting_id):
        # watch() is set before any speaker_jobs row exists, including short recordings.
        with self.lock:
            return meeting_id in self.meetings or self.speakers.store.status(meeting_id)['state'] in ('queued', 'running')

    def watch(self, meeting_id):
        with self.lock:
            if self.scope and self.profiles:
                self.meetings.add(meeting_id)
        self.wake.set()

    def pause(self, meeting_id=None, *, keep_pending=False):
        with self.lock:
            targets = list(self.meetings) if meeting_id is None else [meeting_id]
            if self.inflight in targets:
                self.cancelled.set()
                self.cancelled = threading.Event()
            if not keep_pending:
                self.meetings.difference_update(targets)
            if self.profiles:
                self.state='ready'
        for target in targets:
            self.speakers.store.stop(target)

    def publish_final(self, version, meeting_id, generation, result):
        with self.lock:
            # Clearing a cache keeps historical labels, but no in-flight result may
            # introduce names from the cleared company's templates.
            if version != self.version:
                return False
            return self.speakers.store.finish(meeting_id,generation,result['turns'],result['device'],result.get('identities'))

    def read_window(self, meeting_id, start_ms, end_ms):
        with self.recorder.lock:
            meeting=self.repo.get(meeting_id,internal=True)
            session=self.recorder.session
            live=session is not None and session.meeting_id==meeting_id and session.state in ACTIVE
            if live:
                if session.state!='recording': return None
                rate,available=session.sample_rate,session.frames
                path=self.repo.path(meeting_id,'recording.wav')
            else:
                if meeting['status'] in ACTIVE or not meeting['audioAvailable']: return None
                rate,available=meeting['sampleRate'],meeting['frames']
                path=self.repo.root/meeting['audioPath']
            start,end=round(start_ms*rate/1000),min(available,round(end_ms*rate/1000))
            if end<=start: return None
            with wave.open(str(path),'rb') as audio:
                audio.setpos(start)
                pcm=audio.readframes(end-start)
            if len(pcm)!=(end-start)*2:
                return None
            return pcm,rate

    def process(self, meeting_id, version, scope, profiles, cancelled):
        job=self.transcription.store.job(meeting_id,published=True)
        if not job or job['candidate']: return False
        meeting=self.repo.get(meeting_id,internal=True)
        status=self.speakers.store.status(meeting_id)
        if status['state']=='completed':
            with self.lock: self.meetings.discard(meeting_id)
            return False
        if job['state']=='completed' and meeting['status'] not in ACTIVE:
            if self.speakers.active() or self.transcription.activity()['active']: return False
            with self.lock:
                if version!=self.version or cancelled.is_set(): return False
                self.speakers.start(meeting_id)
                self.meetings.discard(meeting_id)
            return True
        if meeting['status'] in ('pausing','paused','resuming','stopping'): return False
        if self.speakers.active(): return False
        available=job['processedFrames']*1000/meeting['sampleRate']
        start=status.get('processedMs',0)
        if available-start<15_000: return False
        end=min(available,start+15_000)
        context_start=max(0,start-5_000)
        audio=self.read_window(meeting_id,context_start,end)
        if audio is None: return False
        pcm,rate=audio
        with self.lock:
            if version!=self.version or cancelled.is_set(): return False
            generation=self.speakers.store.begin_live(meeting_id,scope)
            if generation is None: return False
            self.state,self.error='processing',None
            self.inflight=meeting_id
        with tempfile.TemporaryDirectory(prefix='paa-speaker-window-') as temporary:
            path=Path(temporary)/'window.wav'
            with wave.open(str(path),'wb') as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate);wav.writeframes(pcm)
            preference=self.transcription.model.status().get('device','gpu')
            result=self.runner({'audio':str(path),'model':str(self.speakers.path),'device':preference,'profiles':profiles},cancelled,lambda _:None,180)
        with self.lock:
            if version!=self.version or cancelled.is_set(): return False
            ambiguous=set(result.get('ambiguousLabels',[]))
            features={label:value for label,value in result.get('embeddings',{}).items() if label not in ambiguous}
            tracks=self.tracks.setdefault(meeting_id,{})
            aliases={}
            for label,value in features.items():
                prior=match(value['templates'],list(tracks.values()),max(3,value['speechSeconds']),threshold=.72,margin=.15)
                if prior: aliases[label]=prior['memberId']
            # A short-window cluster containing two different voices must not
            # become a persistent label whose old words later inherit one name.
            turns=[(a+context_start,b+context_start,label) for a,b,label in result['turns'] if label not in ambiguous]
            mapping=self.speakers.store.publish(meeting_id,generation,turns,result['device'],identities=result.get('identities'),start_ms=context_start,end_ms=end,aliases=aliases)
            if isinstance(mapping,dict):
                accumulated={}
                for label,value in features.items():
                    if label in mapping:
                        key=mapping[label]
                        prior=tracks.get(key,{})
                        combined=prior.get('templates',[])+value['templates']
                        if len(combined)>12:
                            combined=[combined[round(i*(len(combined)-1)/11)] for i in range(12)]
                        # Context is not counted a second time as additional speech.
                        new_speech=value['speechSeconds']*max(0,end-start)/max(1,end-context_start)
                        seconds=prior.get('speechSeconds',0)+new_speech
                        tracks[key]={'memberId':key,'name':key,'templates':combined,'speechSeconds':seconds}
                        identity=match(combined,profiles,seconds)
                        if identity:accumulated[key]=identity
                self.speakers.store.identify(meeting_id,generation,accumulated)
            self.state='ready'
            self.inflight=None
        return True

    def run(self):
        while not self.closed.is_set():
            with self.lock:
                version,scope,profiles=self.snapshot()
                cancelled=self.cancelled
                meetings=list(self.meetings) if profiles and scope else []
            worked=False
            for meeting_id in meetings:
                if cancelled.is_set() or self.closed.is_set(): break
                try:
                    worked=self.process(meeting_id,version,scope,profiles,cancelled)
                except Exception as exc:
                    if cancelled.is_set(): break
                    with self.lock:
                        if version!=self.version: break
                        self.state='failed'
                        self.error=str(exc) if isinstance(exc,DomainError) else '声音匹配暂未完成，录音和文字已保留，可在会议结束后重试区分说话人。'
                        self.meetings.discard(meeting_id)
                    self.speakers.store.stop(meeting_id,self.error)
                finally:
                    with self.lock:
                        if self.inflight==meeting_id:
                            self.inflight=None
                if worked: break
            self.wake.wait(.2 if worked else .7)
            self.wake.clear()

    def shutdown(self):
        self.closed.set();self.cancelled.set();self.wake.set()
        self.thread.join(8)
