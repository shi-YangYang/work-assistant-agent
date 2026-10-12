"""Shared controlled fixtures extracted from test_desktop_voiceprints."""
import base64
import hashlib
import io
import secrets
import wave
from paa_voiceprints import MODEL_ID


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
        wav.writeframes(b'\0\0' * 16000)
    return output.getvalue()


async def start(client):
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    response = await client.post('/api/v1/desktop/login/start', json={'challenge': challenge})
    assert response.status_code == 200, response.text
    return response.json(), verifier


async def token(client):
    request, verifier = await start(client)
    result = await client.post('/api/v1/auth/desktop/requests/' + request['requestId'], json={'approve': True})
    assert result.status_code == 200, result.text
    response = await client.post('/api/v1/desktop/login/exchange', json={'requestId': request['requestId'], 'verifier': verifier})
    assert response.status_code == 200, response.text
    return response.json()['token']


async def enroll(client, member_id, revision=0, *, consent=True):
    return await client.post('/api/v1/settings/voiceprints/' + member_id, data={'consent': str(consent).lower(), 'expectedRevision': str(revision)}, files={'file': ('sample.wav', wav_bytes(), 'audio/wav')})


async def fake_extract(path, settings):
    assert path.is_file()
    return {'modelId': MODEL_ID, 'templates': [[1.] + [0.] * 255], 'speechSeconds': 7.2}
