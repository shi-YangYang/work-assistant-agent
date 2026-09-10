"""Dedicated authored meeting fixture for portable Electron tests, no real user data."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/python'))
from paa_core.audio_store import AudioWriter
from paa_core.repository import Repository
from test_summary import seed

root = Path(sys.argv[1]).resolve()
repo = Repository(root)
mid = seed(repo)
path = repo.path(mid, 'audio.wav')
path.parent.mkdir(parents=True)
writer = AudioWriter(path, 16000)
writer.write(b'\x00\x00' * 16000 * 62)
writer.close()
repo.update(mid, sampleRate=16000, frames=16000 * 62, durationMs=62000, bytes=16000 * 62 * 2, audioPath=f'meetings/{mid}/audio.wav')
print(json.dumps({'meetingId': mid}))
