import asyncio
import base64
import hashlib
import tempfile
import wave
from app.core.errors import problem
from pathlib import Path
from weakref import WeakKeyDictionary

IMAGE_PREVIEW_VERSION = 'image-v1'


AUDIO_PREVIEW_VERSION = 'audio-v1.wav'


MAX_MESSAGE_IMAGE_BLOCKS = 8


MAX_MESSAGE_IMAGE_PIXELS = 16_000_000


MAX_MESSAGE_IMAGE_BYTES = 6 * 1024 * 1024


async def image_process(path, mode='validate'):
    from app.integrations.parsing.process import parse_process
    loop = asyncio.get_running_loop()
    limit = _image_limits.setdefault(loop, asyncio.Semaphore(2))
    async with limit:
        result = await parse_process(path, mode, timeout=30, entrypoint=Path(__file__).parent / 'parsing/image_parser.py', max_output=8 * 1024 * 1024)
    if result.get('status') != 'ready':
        problem(415, result.get('info', {}).get('error', '图片无法转换，请裁剪后重试'))
    return result


def preview_path(settings, identifier, kind='image'):
    version = AUDIO_PREVIEW_VERSION if kind == 'audio' else IMAGE_PREVIEW_VERSION
    return settings.media_dir / f'{identifier}.{version}'


def remove_media(settings, identifier):
    (settings.media_dir / identifier).unlink(missing_ok=True)
    # Known conversion versions only; no untrusted filename/glob path.
    preview_path(settings, identifier).unlink(missing_ok=True)
    preview_path(settings, identifier, 'audio').unlink(missing_ok=True)


_image_limits = WeakKeyDictionary()


_conversion_limits = WeakKeyDictionary()


async def audio_wav(path: Path, settings):
    loop = asyncio.get_running_loop()
    limit = _conversion_limits.setdefault(loop, asyncio.Semaphore(2))
    async with limit:
        return await _audio_wav(path, settings)


async def _audio_wav(path: Path, settings):
    with tempfile.TemporaryDirectory(prefix='paa-audio-') as temp:
        output = Path(temp) / 'audio.wav'
        try:
            process = await asyncio.create_subprocess_exec(settings.ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-threads', '1', '-protocol_whitelist', 'file,pipe', '-i', str(path), '-vn', '-t', '181', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', '-threads', '1', str(output), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        except FileNotFoundError:
            problem(503, '语音处理暂不可用，请联系管理员或发送文字')
        try:
            await asyncio.wait_for(process.wait(), timeout=60)
        except (asyncio.TimeoutError, asyncio.CancelledError) as error:
            if process.returncode is None:
                process.kill()
            await process.wait()
            if isinstance(error, asyncio.CancelledError):
                raise
            problem(422, '语音处理超时，请使用较短录音')
        if process.returncode != 0:
            problem(415, '语音文件无法读取，请使用 MP3、WebM、MP4、AAC 或 WAV')
        with wave.open(str(output)) as audio:
            duration = audio.getnframes() / audio.getframerate()
        if duration <= 0 or duration > 180:
            problem(422, '语音长度须在 0～180 秒之间')
        return output.read_bytes(), duration


def audio_mime(data):
    if data[:4] == b'RIFF' and data[8:12] == b'WAVE':
        return 'audio/wav'
    if data[:4] == b'\x1aE\xdf\xa3':
        return 'audio/webm'
    if data[4:8] == b'ftyp':
        return 'audio/mp4'
    if len(data) > 2 and data[0] == 255 and data[1] & 0xF6 == 0xF0:
        return 'audio/aac'
    if data.startswith(b'ID3') or (len(data) > 2 and data[0] == 255 and data[1] & 0xE0 == 0xE0 and data[1] & 0x06 != 0):
        return 'audio/mpeg'
    problem(415, '请使用 MP3、WebM、MP4、AAC 或 WAV 语音文件')


def data_url(data, mime):
    return f'data:{mime};base64,{base64.b64encode(data).decode()}'


def checksum(data):
    return hashlib.sha256(data).hexdigest()
