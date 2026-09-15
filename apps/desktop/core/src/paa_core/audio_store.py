"""PCM16 WAV storage. A crash can leave complete frames beyond the last header update."""
from __future__ import annotations

import os
import struct
import time
import wave
from pathlib import Path

MAX_PCM_BYTES = 0xFFFFFFFF - 36


class AudioWriter:
    def __init__(self, path: Path, sample_rate: int):
        self.path = path
        self.file = path.open('xb', buffering=0)
        self.wav = wave.open(self.file, 'wb')
        self.wav.setparams((1, 2, sample_rate, 0, 'NONE', 'not compressed'))
        self.wav.writeframes(b'')
        self.frames = 0
        self.last_sync = time.monotonic()

    def write(self, pcm: bytes) -> None:
        if len(pcm) % 2 or self.frames * 2 + len(pcm) > MAX_PCM_BYTES:
            raise OSError('WAV capacity or frame alignment limit')
        self.wav.writeframes(pcm)
        self.frames += len(pcm) // 2
        if time.monotonic() - self.last_sync >= 1:
            os.fsync(self.file.fileno())
            self.last_sync = time.monotonic()

    def sync(self) -> None:
        os.fsync(self.file.fileno())
        self.last_sync = time.monotonic()

    def close(self) -> None:
        try:
            self.wav.close()
            os.fsync(self.file.fileno())
        finally:
            self.file.close()


def inspect_audio(path: Path, sample_rate: int) -> dict:
    with wave.open(str(path), 'rb') as audio:
        frames = audio.getnframes()
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, sample_rate, 'NONE'):
            raise ValueError('Invalid audio format')
        if frames <= 0 or path.stat().st_size != 44 + frames * 2:
            raise ValueError('Incomplete or empty audio')
        return {'frames': frames, 'bytes': frames * 2, 'durationMs': round(frames * 1000 / sample_rate)}


def _recovery_header(original, sample_rate: int) -> tuple[bytes, int]:
    header = original.read(44)
    if len(header) != 44 or header[:4] != b'RIFF' or header[8:16] != b'WAVEfmt ' or header[36:40] != b'data':
        raise ValueError('Unrecognized audio header')
    if struct.unpack('<IHHIIHH', header[16:36]) != (16, 1, 1, sample_rate, sample_rate * 2, 2, 16):
        raise ValueError('Unexpected audio format')
    size = min((os.fstat(original.fileno()).st_size - 44) // 2 * 2, MAX_PCM_BYTES // 2 * 2)
    if size <= 0:
        raise ValueError('No complete audio frames')
    return header, size


def inspect_recoverable_audio(source: Path, sample_rate: int) -> dict:
    # Inspect complete on-disk frames without needing space for a recovery copy.
    with source.open('rb') as original:
        _, size = _recovery_header(original, sample_rate)
    return {'frames': size // 2, 'bytes': size, 'durationMs': round(size * 500 / sample_rate)}


def recover_audio(source: Path, destination: Path, sample_rate: int) -> dict:
    # Only recover this application's canonical 44-byte PCM WAV. Keep the source.
    with source.open('rb') as original:
        header, size = _recovery_header(original, sample_rate)
        staging = destination.with_suffix('.recovering')
        with staging.open('wb') as output:
            output.write(header[:4] + struct.pack('<I', 36 + size) + header[8:40] + struct.pack('<I', size))
            remaining = size
            while remaining:
                data = original.read(min(remaining, 65536))
                if not data:
                    raise ValueError('Audio changed during recovery')
                output.write(data)
                remaining -= len(data)
            output.flush()
            os.fsync(output.fileno())
        staging.replace(destination)
    return inspect_audio(destination, sample_rate)
