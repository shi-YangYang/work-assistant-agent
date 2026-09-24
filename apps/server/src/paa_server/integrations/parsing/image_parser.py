import base64
import io
import json
import math
import runpy
import sys
from pathlib import Path

MAX_PIXELS = 20_000_000


MAX_TILES = 4


MAX_MODEL_PIXELS = 8_000_000


MAX_ENCODED = 3 * 1024 * 1024


PREVIEW_BYTES = 4 * 1024 * 1024


VERSION = 'image-v1'


def encode(image, lossless, limit):
    output = io.BytesIO()
    image.info.clear()
    image.save(output, 'PNG' if lossless else 'JPEG', **({} if lossless else {'quality': 92}))
    if len(output.getvalue()) > limit:
        # Do not silently destroy screenshot detail merely to fit an upload.
        raise ValueError('图片转换后超过处理容量，请裁剪或拆分图片后重试')
    return {'mime': 'image/png' if lossless else 'image/jpeg', 'data': base64.b64encode(output.getvalue()).decode(), 'width': image.width, 'height': image.height}


def convert(path, mode):
    from PIL import Image, ImageOps
    from pillow_heif import register_heif_opener
    register_heif_opener(thumbnails=False, decode_threads=1)
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    with Image.open(path) as source:
        types = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp', 'HEIF': 'image/heic'}
        mime = types.get(source.format)
        if not mime or source.width * source.height > MAX_PIXELS:
            raise ValueError('请使用不超过 2,000 万像素的 JPEG、PNG、WebP 或 HEIC／HEIF 图片')
        warnings = []
        # Pillow HEIF opens the container's primary image; do not iterate frames.
        if getattr(source, 'n_frames', 1) > 1:
            warnings.append('多图或动态内容仅使用主图／首帧')
        source.load()
        original_format = source.format
        oriented = ImageOps.exif_transpose(source)
        width, height = oriented.size
        if 'A' in oriented.getbands() or 'transparency' in oriented.info:
            rgba = oriented.convert('RGBA')
            image = Image.new('RGB', rgba.size, 'white')
            image.paste(rgba, mask=rgba.getchannel('A'))
        else:
            image = oriented.convert('RGB')
        image.info.clear()
    result = {'status': 'ready', 'mime': mime, 'width': width, 'height': height, 'warnings': warnings, 'version': VERSION}
    if mode == 'validate':
        return result
    lossless = original_format == 'PNG'
    if mode == 'preview':
        # Separate display preview; never apply model tile sizing to the original.
        scale = min(1, 8192 / max(width, height), math.sqrt(12_000_000 / (width * height)))
        if scale < 1:
            image = image.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.LANCZOS)
        result['preview'] = encode(image, lossless, PREVIEW_BYTES)
        return result
    boxes = []
    if height > width * 2.5 or width > height * 2.5:
        vertical = height > width
        length, cross = (height, width) if vertical else (width, height)
        # Preserve narrow screenshot pixels; reduce only the cross-axis above1600.
        scale = min(1, 1600 / cross)
        span = max(1, int(2048 / scale))
        needed = math.ceil(length / span)
        for index in range(min(needed, MAX_TILES)):
            start, end = index * span, min(length, (index + 1) * span)
            boxes.append((0, start, width, end) if vertical else (start, 0, end, height))
        if needed > MAX_TILES:
            warnings.append(f'长图仅覆盖前 {MAX_TILES} 段，后续未读取；请裁剪剩余部分补充发送')
    else:
        boxes = [(0, 0, width, height)]
    tiles, pixels, encoded = [], 0, 0
    for box in boxes:
        tile = image.crop(box)
        tile.thumbnail((2560, 2560) if len(boxes) == 1 else (2048, 2048), Image.Resampling.LANCZOS)
        if pixels + tile.width * tile.height > MAX_MODEL_PIXELS:
            warnings.append('已达到图片像素预算，后续区域未读取；请裁剪补充发送')
            break
        item = encode(tile, lossless, MAX_ENCODED)
        size = len(base64.b64decode(item['data']))
        if encoded + size > MAX_ENCODED:
            warnings.append('已达到图片编码预算，后续区域未读取；请裁剪补充发送')
            break
        pixels += tile.width * tile.height
        encoded += size
        tiles.append({**item, 'box': list(box)})
    if not tiles:
        raise ValueError('图片超出处理预算，请裁剪后重试')
    result.update(tiles=tiles, pixels=pixels, bytes=encoded, complete=len(tiles) == len(boxes) and not any('未读取' in warning for warning in warnings))
    return result


def main():
    limits = runpy.run_path(str(Path(__file__).with_name('document_parser.py')))
    limits['resource_limits']()
    try:
        result = convert(sys.argv[1], sys.argv[2])
    except ValueError as error:
        result = {'status': 'failed', 'info': {'error': str(error)}}
    except Exception:
        result = {'status': 'failed', 'info': {'error': '图片无法解码或超出资源限制，请重新导出或裁剪后重试'}}
    print(json.dumps(result, ensure_ascii=False))

if __name__ == '__main__':
    main()
