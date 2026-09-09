"""Explicit Electron test launcher. Only this test file injects synthetic input."""
import os
import sys
import threading
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/python'))
from paa_core.audio_store import AudioWriter
from paa_core.protocol import CoreService, serve
from test_recording import FakeInput


class ContinuousStream:
    def __init__(self, callback, block):
        self.callback, self.block = callback, block
        self.active = False
        self.stop_event = threading.Event()
    def start(self):
        self.active = True
        def produce():
            while not self.stop_event.is_set():
                self.callback(b'\0\0' * self.block, self.block, None, False)
                self.stop_event.wait(self.block / 48000)
        self.thread = threading.Thread(target=produce, daemon=True)
        self.thread.start()
    def stop(self):
        self.stop_event.set()
        self.thread.join()
        self.active = False
    close = stop
    abort = stop


class ContinuousInput(FakeInput):
    def stream(self, _device, _rate, block, callback):
        return ContinuousStream(callback, block)


root = Path(sys.argv[sys.argv.index('--data-dir') + 1])
service = CoreService(root, ContinuousInput())
if os.environ.get('PAA_FIXTURE_FAIL_CLOSE') == '1':
    class FailingClose(AudioWriter):
        def close(self):
            super().close()
            raise OSError('Synthetic close failure')
    service.recorder.writer_factory = FailingClose
serve(sys.stdin.buffer, sys.stdout.buffer, service)
