"""Only execution-local inputs and atomic final output files."""
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


def filename(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 180 or value in ('.', '..') or any(c in value for c in '/\\\x00') or any(ord(c) < 32 for c in value):
        raise ValueError('文件名无效，不能包含目录或控制字符')
    return value


def input_path(value, suffixes):
    root = (Path.cwd() / 'inputs').resolve()
    path = root / filename(value)
    if path.is_symlink() or not path.is_file() or path.resolve().parent != root:
        raise ValueError('输入文件不存在或越界')
    if path.suffix.lower() not in suffixes:
        raise ValueError('输入文件格式不支持')
    return path


@contextmanager
def output_file(name, suffix):
    filename(name)
    if Path(name).suffix.lower() != suffix:
        raise ValueError('文件扩展名与目标格式不一致')
    root = Path.cwd()
    output, temporary = root / 'output', root / 'tmp'
    for directory in (output, temporary):
        if directory.is_symlink():
            raise ValueError('工作目录不可为链接')
        directory.mkdir(exist_ok=True)
    final = output / name
    if final.exists() or final.is_symlink():
        raise ValueError('目标文件已存在，请使用新文件名')
    temp = temporary / (uuid4().hex + suffix)
    try:
        yield temp
        if temp.is_symlink() or not temp.is_file() or not 0 < temp.stat().st_size <= 32 * 1024 * 1024:
            raise ValueError('生成文件为空或超过32 MiB')
        temp.replace(final)
    finally:
        temp.unlink(missing_ok=True)


def image_path(value):
    from PIL import Image
    path = input_path(value, {'.png', '.jpg', '.jpeg', '.webp'})
    with Image.open(path) as image:
        width, height = image.size
        if width <= 0 or height <= 0 or width * height > 40_000_000:
            raise ValueError('图片尺寸超出限制')
        image.verify()
    return path, width, height
