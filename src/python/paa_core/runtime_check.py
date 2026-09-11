"""Explicit frozen-runtime diagnostic; only synthetic fixtures in a fresh temporary directory."""
import hashlib
import json
import os
import platform
import socket
import ssl
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
import wave
from pathlib import Path

from .asr_worker import ASRWorker, DEFAULT_CONFIG, WhisperProvider
from .recorder import NativeInput, Recorder
from .repository import Repository

SPEECH_URL = 'https://raw.githubusercontent.com/wenet-e2e/wenet/d17059667d6afe0680d19b3a4948ab825ef25105/test/resources/aishell-BAC009S0724W0121.wav'
SPEECH_SHA256 = '2f9fc9c912bb71c85fb286cb88b599c81efb8f727c727a5ea8f6d1c89c55ac13'


class OfflineProvider(WhisperProvider):
    def __init__(self, path, config):
        def blocked(*_args, **_kwargs):
            raise AssertionError('The frozen ASR worker must remain offline')
        socket.socket.connect = blocked
        super().__init__(path, config)


class FixtureStream:
    def __init__(self, callback, block):
        self.callback, self.block = callback, block
        self.done = threading.Event()
        self.active = False
    def start(self):
        self.active = True
        def run():
            while not self.done.is_set():
                self.callback(b'\1\0' * self.block, self.block, None, False)
                self.done.wait(self.block / 16000)
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
    def stop(self):
        self.done.set()
        self.thread.join(timeout=2)
        self.active = False
    close = stop
    abort = stop


class FixtureInput:
    def device(self): return 0, 'Runtime diagnostic fixture', 16000
    def stream(self, _device, _rate, block, callback): return FixtureStream(callback, block)


def wait(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.02)
    raise AssertionError('Runtime diagnostic timed out')


def check(model_path, audio_path):
    assert getattr(sys, 'frozen', False), 'Run this check from the frozen executable'
    assert platform.python_version().startswith('3.12.')
    assert model_path and audio_path, 'Provide the public fixture and prepared small model'
    import certifi
    import av
    import ctranslate2
    import onnxruntime
    import tokenizers
    import faster_whisper
    assert Path(certifi.where()).is_file()
    assert (Path(faster_whisper.__file__).parent / 'assets/silero_vad_v6.onnx').is_file()
    assert NativeInput().sd.get_portaudio_version()[0] > 0
    # A fixed public resource exercises the bundled certificate store; no credentials or paid API.
    with urllib.request.urlopen(SPEECH_URL, context=ssl.create_default_context(cafile=certifi.where()), timeout=30) as response:
        assert hashlib.sha256(response.read(200000)).hexdigest() == SPEECH_SHA256
    assert hashlib.sha256(audio_path.read_bytes()).hexdigest() == SPEECH_SHA256
    with wave.open(str(audio_path), 'rb') as source:
        pcm, rate = source.readframes(source.getnframes()), source.getframerate()
    worker = ASRWorker(OfflineProvider)
    started = time.monotonic()
    try:
        words = worker.infer(model_path, pcm, rate, DEFAULT_CONFIG)
        text = ''.join(word['text'] for word in words)
        assert '中介协会分析' in text, text
        assert worker.process and worker.process.pid != os.getpid()
        worker_pid = worker.process.pid
    finally:
        worker.shutdown()
    with tempfile.TemporaryDirectory(prefix='paa runtime 会议 ') as directory:
        repository = Repository(Path(directory))
        recorder = Recorder(repository, FixtureInput())
        try:
            mid = recorder.start(str(uuid.uuid4()))['meetingId']
            wait(lambda: recorder.status()['elapsedMs'] > 0)
            recorder.pause(mid)
            wait(lambda: recorder.status()['state'] == 'paused')
            paused = recorder.status()['elapsedMs']
            time.sleep(.15)
            assert recorder.status()['elapsedMs'] == paused
            recorder.resume(mid)
            wait(lambda: recorder.status()['elapsedMs'] > paused)
            recorder.stop(mid)
            wait(lambda: recorder.session.finished.is_set())
            meeting = repository.get(mid)
            assert meeting['status'] == 'completed' and meeting['audioAvailable']
        finally:
            recorder.shutdown()
    print(json.dumps({'frozen': True, 'executable': sys.executable, 'python': platform.python_version(),
                      'platform': platform.platform(), 'asrWorkerPid': worker_pid, 'inferenceSeconds': round(time.monotonic() - started, 3),
                      'offlineAsrText': text, 'vad': True, 'certificateHttps': True, 'syntheticPauseResume': True,
                      'nativeImports': [av.__version__, ctranslate2.__version__, onnxruntime.__version__, tokenizers.__version__]}, ensure_ascii=True), flush=True)
