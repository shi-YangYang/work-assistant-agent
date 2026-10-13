"""Deterministic configured sizes; no model calls or image resampling."""
import math
import re
from fractions import Fraction
from app.integrations.models.transport import ProviderError
from .profiles import WAN_MODELS, pixels

PRESETS = {'1:1': (2048, 2048), '16:9': (2688, 1536), '9:16': (1536, 2688), '4:3': (2368, 1728), '3:4': (1728, 2368)}
USES = {'avatar': '1:1', 'icon': '1:1', 'desktop_wallpaper': '16:9', 'cover': '16:9', 'phone_wallpaper': '9:16', 'poster': '3:4'}


def invalid(message):
    raise ProviderError('image_size', message, sent=False)


def validate(width, height, max_edge=2048):
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0 or not 768 ** 2 <= width * height <= max_edge ** 2 or not 1 / 8 <= width / height <= 8:
        invalid(f'当前模型图片总像素需在 768²～{max_edge}² 之间，宽高比在 1:8～8:1 之间；请指定支持的尺寸。')
    return f'{width}*{height}'


def wan_size(*, width=None, height=None, aspect='', resolution='', use='', max_edge=2048):
    if resolution not in (('', '1K', '2K', '4K') if max_edge == 4096 else ('', '1K', '2K')):
        supported = '1K、2K、4K' if max_edge == 4096 else '1K、2K，不支持 4K'
        invalid(f'当前图片模型支持 {supported}；请确认可接受的尺寸后再生成。')
    if use and use not in USES:
        invalid('图片用途无效，请直接指定比例或尺寸。')
    ratio = None
    if aspect:
        if not re.fullmatch(r'[1-9]\d{0,4}:[1-9]\d{0,4}', aspect):
            invalid('请使用明确宽高比，例如 16:9。')
        a, b = map(int, aspect.split(':'))
        ratio = Fraction(a, b)
        if not Fraction(1, 8) <= ratio <= 8:
            invalid('图片宽高比需在 1:8～8:1 之间。')
        aspect = f'{ratio.numerator}:{ratio.denominator}'
    if width is not None or height is not None:
        size = validate(width, height, max_edge)
        if ratio is not None and Fraction(width, height) != ratio:
            invalid('指定的像素尺寸与比例不一致，请确认使用哪一个。')
        return size
    aspect = aspect or USES.get(use, '')
    if not aspect:
        return resolution or None
    if resolution != '1K' and aspect in PRESETS:
        factor = 2 if resolution == '4K' else 1
        return validate(*(value * factor for value in PRESETS[aspect]), max_edge)
    a, b = map(int, aspect.split(':'))
    edge = {'1K': 1024, '4K': 4096}.get(resolution, 2048)
    ratio = Fraction(a, b)
    a, b = ratio.numerator, ratio.denominator
    scale = math.floor(edge / math.sqrt(a * b))
    if scale >= 1 and a * b * scale ** 2 >= 768 ** 2:
        width, height = a * scale, b * scale
    else:
        # Large coprime ratios need pixel rounding, not a different preset.
        width, height = math.floor(edge * math.sqrt(ratio)), math.floor(edge / math.sqrt(ratio))
        width, height = min(width, height * 8), min(height, width * 8)
    return validate(width, height, max_edge)


def ratio_value(aspect):
    if not re.fullmatch(r'[1-9]\d{0,4}:[1-9]\d{0,4}', aspect):
        invalid('请使用明确宽高比，例如 16:9。')
    return Fraction(*map(int, aspect.split(':')))


def bounded_size(width, height):
    if type(width) is not int or type(height) is not int:
        invalid('请同时填写正整数图片宽度和高度。')
    try:
        pixels(f'{width}*{height}')
    except ValueError as error:
        invalid(str(error))
    return f'{width}*{height}'


def normalize(*, config=None, width=None, height=None, aspect='', resolution='', use=''):
    # No config remains the original Wan contract for internal legacy callers.
    config = config or {'model': 'wan2.7-image'}
    settings = config.get('imageSettings') or {}
    mode = settings.get('sizeMode', 'auto')
    if mode == 'auto' and config['model'] in WAN_MODELS:
        return wan_size(width=width, height=height, aspect=aspect, resolution=resolution, use=use,
                        max_edge=WAN_MODELS[config['model']])
    if use and use not in USES:
        invalid('图片用途无效，请直接指定比例或尺寸。')
    ratio = ratio_value(aspect) if aspect else None
    exact = bounded_size(width, height) if width is not None or height is not None else None
    if exact and ratio is not None and Fraction(width, height) != ratio:
        invalid('指定的像素尺寸与比例不一致，请确认使用哪一个。')
    if mode == 'fixed':
        choices = settings.get('sizes', [])
        supported = '、'.join(choices)
        if exact:
            if exact not in choices:
                invalid(f'此模型支持的尺寸为 {supported}；指定尺寸不可用，请确认后再生成。')
            return exact
        ratio = ratio or (ratio_value(USES[use]) if use else None)
        candidates = [size for size in choices if ratio is None or Fraction(*pixels(size)) == ratio]
        if resolution:
            edge = {'1K': 1024, '2K': 2048, '4K': 4096}.get(resolution)
            candidates = [size for size in candidates if edge and math.prod(pixels(size)) == edge ** 2]
        if not candidates:
            invalid(f'此模型没有匹配该比例或分辨率的尺寸，可选尺寸：{supported}；请确认后再生成。')
        default = settings.get('defaultSize')
        return default if default in candidates else candidates[0]
    # Unknown models and explicit provider mode do not inherit Wan limits or defaults.
    if exact:
        return exact
    if aspect or resolution:
        invalid('此模型未配置比例或分辨率映射，请指定明确宽高，或让管理员配置可选尺寸。')
    return None


def wire_size(config, size):
    if size is None:
        size = normalize(config=config)
        settings = config.get('imageSettings') or {}
        if size is None and settings.get('sizeMode', 'auto') == 'auto' and config['model'] in WAN_MODELS:
            size = '2K'
    return {'1K': '1024*1024', '2K': '2048*2048', '4K': '4096*4096'}.get(size, size)
