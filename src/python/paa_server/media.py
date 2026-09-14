import asyncio
import base64
import hashlib
import io
from pathlib import Path
import tempfile
import wave
from PIL import Image, UnidentifiedImageError
from .service import problem

Image.MAX_IMAGE_PIXELS = 20_000_000
IMAGE_TYPES = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp'}


def image_input(data: bytes):
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in IMAGE_TYPES or image.width * image.height > 20_000_000:
                problem(415, '请使用不超过 2,000 万像素的 JPEG、PNG 或 WebP 图片')
            mime = IMAGE_TYPES[image.format]
            image.load()
            image.thumbnail((2048, 2048))
            buffer = io.BytesIO()
            image.convert('RGB').save(buffer, 'JPEG', quality=85)
            return mime, buffer.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        problem(415, '图片无法读取，请转换为 JPEG、PNG 或 WebP 后重试')


async def audio_wav(path: Path, settings):
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
            problem(415, '语音文件无法读取，请使用 WebM、MP4、AAC 或 WAV')
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
    problem(415, '请使用 WebM、MP4、AAC 或 WAV 语音文件')


def data_url(data, mime):
    return f'data:{mime};base64,{base64.b64encode(data).decode()}'


def checksum(data):
    return hashlib.sha256(data).hexdigest()
