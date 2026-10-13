"""Private image downloads with checked DNS, redirects and bounded PNG decoding."""
import asyncio
import hashlib
import httpx
import io
import ipaddress
from types import SimpleNamespace
from urllib.parse import urljoin, urlsplit
from PIL import Image
from .profiles import MAX_EDGE, MAX_PIXELS
from app.integrations.models.transport import CheckedBackend, ProviderError, allowed_address

MAX_BYTES = 32 * 1024 * 1024


def checked_url(value):
    try:
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.port not in (None, 443) or any(ord(c) < 33 for c in value) or '\\' in value:
            raise ValueError()
    except ValueError:
        raise ProviderError('image_url', '图片下载地址无效') from None
    try:
        ipaddress.ip_address(parsed.hostname)
    except ValueError:
        pass
    else:
        if not allowed_address(parsed.hostname):
            raise ProviderError('image_url', '图片下载地址指向受限制网络')
    return value


def metadata(data, name='image.png'):
    if not 0 < len(data) <= MAX_BYTES or not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ProviderError('image_format', '图片内容或大小不符合 PNG 要求')
    try:
        with Image.open(io.BytesIO(data)) as picture:
            width, height = picture.size
            if picture.format != 'PNG' or getattr(picture, 'n_frames', 1) != 1 or width <= 0 or height <= 0 or width * height > MAX_PIXELS or max(width, height) > MAX_EDGE:
                raise ValueError()
            picture.verify()
        with Image.open(io.BytesIO(data)) as picture:
            picture.load()
    except Exception:
        raise ProviderError('image_format', '图片文件损坏或像素超出支持范围') from None
    sha = hashlib.sha256(data).hexdigest()
    return {'id': sha, 'sha256': sha, 'name': name, 'mimeType': 'image/png', 'size': len(data), 'width': width, 'height': height}


async def download(url):
    transport = httpx.AsyncHTTPTransport(trust_env=False, retries=0)
    transport._pool._network_backend = CheckedBackend(SimpleNamespace(model_allowed_origins=()))
    # No model key, cookies or deployment-private allowlist reaches file hosts.
    async with asyncio.timeout(60), httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False, timeout=httpx.Timeout(30, connect=10), headers={'Accept-Encoding': 'identity'}) as http:
        for _ in range(5):
            checked_url(url)
            async with http.stream('GET', url) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.headers.get('location', ''))
                    continue
                if response.status_code != 200:
                    if response.status_code in (404, 410):
                        raise ProviderError('image_expired', '原图片结果已过期或不可用，无法恢复；没有重新生成', response.status_code)
                    raise ProviderError('image_download', '图片已生成，但暂时无法下载；重试将读取原图片，不重新生成', response.status_code)
                if response.headers.get('content-encoding', 'identity').lower() != 'identity':
                    raise ProviderError('image_format', '图片返回了不支持的压缩内容')
                if response.headers.get('content-type', '').split(';')[0].lower() not in ('image/png', 'application/octet-stream'):
                    raise ProviderError('image_format', '下载结果不是 PNG 图片')
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise ProviderError('image_format', '图片文件过大')
                result = bytes(data)
                return result, await asyncio.to_thread(metadata, result)
    raise ProviderError('image_url', '图片下载重定向次数过多')
