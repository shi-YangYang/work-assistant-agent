"""Model capabilities are separate from the two supported wire protocols."""
import re
from urllib.parse import urlsplit
from app.integrations.models.transport import ProviderError

WAN_MODELS = {'wan2.7-image': 2048, 'wan2.7-image-pro': 4096}
MAX_PIXELS = 4096 ** 2
MAX_EDGE = 16384


def native_host(host):
    return host in ('dashscope.aliyuncs.com', 'dashscope-intl.aliyuncs.com') or bool(re.fullmatch(r'[a-zA-Z0-9-]+\.(cn-beijing|ap-southeast-1)\.maas\.aliyuncs\.com', host or ''))


def api_mode(config):
    selected = (config.get('imageSettings') or {}).get('api', 'auto')
    if selected in ('multimodal-sync', 'image-async'):
        return selected
    if selected == 'auto' and config['model'] in WAN_MODELS:
        host = urlsplit(config['baseUrl']).hostname
        if host == 'token-plan.cn-beijing.maas.aliyuncs.com':
            return 'multimodal-sync'
        if native_host(host):
            return 'image-async'
    raise ProviderError('protocol', '请在图片模型设置中选择同步多模态或异步图片接口；当前模型或服务没有自动匹配规则', sent=False)


def pixels(value):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9]\d{0,4}\*[1-9]\d{0,4}', value):
        raise ValueError('尺寸请填写正整数宽*高，例如 1024*1024')
    width, height = map(int, value.split('*'))
    if max(width, height) > MAX_EDGE or width * height > MAX_PIXELS:
        raise ValueError('图片尺寸不能超过 16,777,216 总像素或 16,384 单边像素')
    return width, height


def validate_settings(value, model):
    if value.get('api', 'auto') == 'auto' and model not in WAN_MODELS:
        raise ValueError('此模型没有自动接口规则，请选择同步多模态或异步图片接口')
    choices = value.get('sizes', [])
    if len(choices) > 16 or len(set(choices)) != len(choices):
        raise ValueError('可选尺寸最多 16 个，且不能重复')
    for size in choices:
        pixels(size)
    if value.get('sizeMode', 'auto') == 'fixed':
        if not choices or value.get('defaultSize') not in choices:
            raise ValueError('固定尺寸需要至少一个尺寸，默认尺寸必须属于可选尺寸')
    elif choices or value.get('defaultSize') is not None:
        raise ValueError('只有固定尺寸模式接受可选尺寸和默认尺寸')
