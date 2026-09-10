"""Required macOS/Windows integration: pinned public speech and real small CPU inference."""
import hashlib
import json
import platform
import sys
import time
import urllib.request
import uuid
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/python'))
from paa_core.protocol import CoreService
from paa_core.model_manager import MODEL_ID, REVISION, verify_files
from paa_core.asr_worker import DEFAULT_CONFIG, ASRWorker, WhisperProvider
from paa_core.transcription import Transcription

SPEECH_URL = 'https://raw.githubusercontent.com/wenet-e2e/wenet/d17059667d6afe0680d19b3a4948ab825ef25105/test/resources/aishell-BAC009S0724W0121.wav'
SPEECH_SHA256 = '2f9fc9c912bb71c85fb286cb88b599c81efb8f727c727a5ea8f6d1c89c55ac13'
REFERENCE = '广州市房地产中介协会分析'


class OfflineProvider(WhisperProvider):
    def __init__(self, path, config):
        import socket
        def blocked(*args, **kwargs):
            raise AssertionError('Network is forbidden inside the ASR worker')
        socket.socket.connect = blocked
        super().__init__(path, config)


def transcription_factory(repository, recorder):
    return Transcription(repository, recorder, worker=ASRWorker(OfflineProvider))


def wait(predicate, timeout=90):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        time.sleep(.2)
    raise AssertionError('Real ASR integration timed out')


def main():
    root=Path('artifacts/spec003/real-asr').resolve()
    root.mkdir(parents=True,exist_ok=True)
    service=CoreService(root, transcription_factory=transcription_factory)
    assert service.transcription, service.storage_error
    model=service.transcription.model
    started=time.monotonic()
    try:
        if model.status()['state']=='missing':model.download()
        def ready():
            state=model.status()
            if state['state']=='error':raise AssertionError(state['error'])
            return state['state']=='ready'
        wait(ready,900)
        load_seconds=time.monotonic()-started
        verify_files(model.path)
        sample=root/'public-speech.wav'
        if not sample.exists():
            with urllib.request.urlopen(SPEECH_URL,timeout=30) as response:
                data=response.read(200000)
            assert hashlib.sha256(data).hexdigest()==SPEECH_SHA256
            sample.write_bytes(data)
        assert hashlib.sha256(sample.read_bytes()).hexdigest()==SPEECH_SHA256
        mid=str(uuid.uuid4())
        service.repository.create(mid,str(uuid.uuid4()))
        path=service.repository.path(mid,'audio.wav');path.parent.mkdir(parents=True)
        path.write_bytes(sample.read_bytes())
        with wave.open(str(path),'rb') as audio:frames=audio.getnframes();rate=audio.getframerate()
        service.repository.update(mid,status='completed',sampleRate=rate,frames=frames,bytes=frames*2,
                                  durationMs=round(frames*1000/rate),audioPath=f'meetings/{mid}/audio.wav')
        # A worker uses only the local pinned model. Network is blocked after preparation.
        def no_network(*args,**kwargs):raise AssertionError('Unexpected network request during local inference')
        import socket
        original_connect=socket.socket.connect
        socket.socket.connect=no_network
        try:
            started=time.monotonic();service.transcription.start(mid)
            def done():
                state=service.transcription.status(mid)
                if state['state']=='failed':raise AssertionError(state['error'])
                return state['state']=='completed'
            wait(done)
            elapsed=time.monotonic()-started
        finally:socket.socket.connect=original_connect
        segments=service.transcription.store.page(mid)['segments']
        text=''.join(segment['text'] for segment in segments)
        normalized=''.join(character for character in text if character.isalnum())
        previous=list(range(len(normalized)+1))
        for i, expected in enumerate(REFERENCE,1):
            current=[i]
            for j, actual in enumerate(normalized,1):current.append(min(current[-1]+1,previous[j]+1,previous[j-1]+(expected!=actual)))
            previous=current
        cer=previous[-1]/len(REFERENCE)
        assert cer<=0.20 and '中介协会分析' in normalized, (text,cer)
        assert service.transcription.status(mid)['processedMs']==round(frames*1000/rate)
        assert all(0<=segment['startMs']<=segment['endMs']<=round(frames*1000/rate) for segment in segments)
        service.transcription.start(mid)
        assert service.transcription.store.page(mid)['segments']==segments
        history_id=str(uuid.uuid4())
        service.repository.create(history_id,str(uuid.uuid4()))
        history_path=service.repository.path(history_id,'audio.wav');history_path.parent.mkdir(parents=True)
        history_path.write_bytes(sample.read_bytes())
        service.repository.update(history_id,status='completed',sampleRate=rate,frames=frames,bytes=frames*2,durationMs=round(frames*1000/rate),audioPath=f'meetings/{history_id}/audio.wav')
        resume_id=str(uuid.uuid4())
        service.repository.create(resume_id,str(uuid.uuid4()))
        resume_path=service.repository.path(resume_id,'audio.wav');resume_path.parent.mkdir(parents=True)
        with wave.open(str(sample),'rb') as source: speech=source.readframes(frames)
        with wave.open(str(resume_path),'wb') as audio:
            audio.setparams((1,2,rate,0,'NONE','not compressed'));audio.writeframes(speech*4)
        service.repository.update(resume_id,status='completed',sampleRate=rate,frames=frames*4,bytes=frames*8,durationMs=round(frames*4000/rate),audioPath=f'meetings/{resume_id}/audio.wav')
        result={'resumeId':resume_id,'cer':cer,'historyId':history_id,'platform':platform.platform(),'python':platform.python_version(),'modelId':MODEL_ID,'revision':REVISION,
                'config':DEFAULT_CONFIG,'modelPrepareSeconds':load_seconds,'inferenceSeconds':elapsed,
                'audioSeconds':frames/rate,'source':SPEECH_URL,'sha256':SPEECH_SHA256,'reference':REFERENCE,
                'text':text,'segments':segments,'meetingId':mid,'dataRoot':str(root)}
        Path('artifacts/spec003/real-asr.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(result,ensure_ascii=False),flush=True)
    finally:service.transcription.shutdown();service.recorder.shutdown()


if __name__=='__main__':main()
