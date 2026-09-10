"""Single managed spawn worker. Only bounded audio windows cross its private pipe."""
from __future__ import annotations

import io
import multiprocessing
import os
import threading
import time
import wave
from contextlib import nullcontext

from .repository import DomainError

DEFAULT_CONFIG = {'chunkSeconds': 10, 'contextSeconds': 4, 'language': 'zh', 'beamSize': 5,
                  'cpuThreads': 4, 'computeType': 'int8', 'version': 1}


class InferenceToken:
    """A cancelled scheduling generation cannot be revived by a later continue request."""
    def __init__(self):
        self.lock = threading.Lock()
        self.cancelled = threading.Event()

    def cancel(self):
        with self.lock:
            self.cancelled.set()


class WhisperProvider:
    def __init__(self, path, config=DEFAULT_CONFIG):
        # These switches also prevent future library changes from silently fetching assets.
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
        from faster_whisper import WhisperModel
        self.model = WhisperModel(str(path), device='cpu', compute_type=config['computeType'],
                                  cpu_threads=config['cpuThreads'], num_workers=1, local_files_only=True)
        self.config = config

    def transcribe(self, pcm, sample_rate):
        from faster_whisper.audio import decode_audio
        encoded = io.BytesIO()
        with wave.open(encoded, 'wb') as wav:
            wav.setparams((1, 2, sample_rate, 0, 'NONE', 'not compressed'))
            wav.writeframes(pcm)
        encoded.seek(0)
        audio = decode_audio(encoded, sampling_rate=16000)
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        # Decode each detected speech interval independently. Concatenating different speakers
        # into one Whisper window can end decoding after the first utterance and lose later speech.
        intervals = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=500,
                                                          speech_pad_ms=200, max_speech_duration_s=20))
        words = []
        for interval in intervals:
            offset = interval['start'] / 16000
            segments, _info = self.model.transcribe(
                audio[interval['start']:interval['end']], language=self.config['language'], task='transcribe',
                beam_size=self.config['beamSize'], temperature=0, word_timestamps=True,
                vad_filter=False, condition_on_previous_text=False, initial_prompt='简体中文')
            for segment in segments:
                for word in segment.words or []:
                    if len(words) >= 500:
                        raise ValueError('ASR output exceeds a bounded audio window')
                    words.append({'start': offset + float(word.start), 'end': offset + float(word.end), 'text': word.word[:300]})
        return words


def worker_main(connection, parent_pid, provider_class):
    # Parent EOF / death must not leave an idle inference process behind after a core crash.
    def parent_guard():
        while True:
            time.sleep(0.5)
            if (multiprocessing.parent_process() and not multiprocessing.parent_process().is_alive()) or os.getppid() != parent_pid:
                os._exit(0)
    threading.Thread(target=parent_guard, daemon=True).start()
    provider = None
    try:
        while True:
            command = connection.recv()
            if command['op'] == 'stop':
                break
            try:
                if command['op'] == 'load':
                    provider = provider_class(command['path'], command['config'])
                    response = {'ok': True}
                elif command['op'] == 'infer' and provider:
                    response = {'ok': True, 'words': provider.transcribe(command['pcm'], command['sampleRate'])}
                else:
                    raise ValueError('Unknown worker operation')
            except Exception as exc:
                response = {'ok': False, 'kind': type(exc).__name__}
            connection.send(response)
    except (EOFError, OSError):
        pass
    finally:
        connection.close()


class ASRWorker:
    def __init__(self, provider_class=WhisperProvider, timeout=90):
        self.provider_class = provider_class
        self.timeout = timeout
        self.lock = threading.Lock()
        self.process = None
        self.connection = None
        self.loaded = None
        self.closed = False
        self.interrupted = threading.Event()

    def check_cancelled(self, token):
        if self.closed or (token is not None and token.cancelled.is_set()):
            raise DomainError('transcription_paused', '转写已暂停，可以稍后继续。')

    def _request(self, command, token=None):
        self.check_cancelled(token)
        if not self.process or not self.process.is_alive():
            self.reset()
            ctx = multiprocessing.get_context('spawn')
            parent, child = ctx.Pipe()
            self.process = ctx.Process(target=worker_main, args=(child, os.getpid(), self.provider_class), daemon=True)
            self.process.start()
            child.close()
            self.connection = parent
        try:
            # Only dispatch is atomic with cancellation. Never hold this lock while
            # waiting for model loading / inference; the private pipe carries one bounded request.
            with token.lock if token is not None else nullcontext():
                self.check_cancelled(token)
                self.interrupted.clear()
                self.connection.send(command)
            deadline = time.monotonic() + self.timeout
            while not self.connection.poll(0.1):
                self.check_cancelled(token)
                if self.closed or self.interrupted.is_set() or not self.process.is_alive() or time.monotonic() >= deadline:
                    raise TimeoutError('Worker interrupted or timed out')
            result = self.connection.recv()
            self.check_cancelled(token)
            if not result.get('ok'):
                raise RuntimeError(result.get('kind', 'Worker error'))
            return result
        except DomainError:
            self.reset()
            raise
        except (OSError, EOFError, TimeoutError, RuntimeError) as exc:
            self.reset()
            raise DomainError('asr_failed', '本地转写未完成，请检查模型与可用内存后继续；录音和已保存文字保留。') from exc

    def load(self, path, config=DEFAULT_CONFIG, token=None):
        with self.lock:
            self.check_cancelled(token)
            key = (str(path), tuple(sorted(config.items())))
            if key != self.loaded or not self.process or not self.process.is_alive():
                self._request({'op': 'load', 'path': str(path), 'config': config}, token)
                self.loaded = key

    def infer(self, path, pcm, sample_rate, config, token=None):
        self.load(path, config, token)
        with self.lock:
            return self._request({'op': 'infer', 'pcm': pcm, 'sampleRate': sample_rate}, token)['words']

    def reset(self, graceful=False):
        if graceful and self.process and self.process.is_alive() and self.connection:
            try:
                self.connection.send({'op': 'stop'})
                self.process.join(timeout=3)
            except (OSError, EOFError):
                pass
        if self.process:
            if self.process.is_alive():
                self.process.terminate()
            self.process.join(timeout=2)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=2)
            self.process.close()
        if self.connection:
            self.connection.close()
        self.process = self.connection = self.loaded = None

    def interrupt(self):
        self.interrupted.set()

    def shutdown(self):
        self.closed = True
        with self.lock:
            self.reset(graceful=True)
