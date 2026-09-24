import re
from app.integrations.models.transport import ProviderError
from app.modules.model_services.schemas import parameters
from urllib.parse import urlsplit


def request_options(model, preset_id=None):
    selected = model.get('selectedPresetId') if preset_id is None else preset_id
    preset = next((p for p in model.get('presets', []) if p['id'] == selected), None)
    if selected and not preset:
        raise ProviderError('protocol', '选择的推理预设不存在')
    return parameters(({'reasoning_effort': preset['value']} if preset['mode'] == 'simple' else preset['parameters']) if preset else {})


def reply_review_config(config, *, reasoning=False):
    """Use bounded verification only where the provider protocol is known.

    Keep the frozen user configuration intact. Unknown gateways/models retain
    their parameters; OpenAI compatibility alone does not imply thinking support.
    """
    host = urlsplit(config['baseUrl']).hostname or ''
    model = config['model'].lower()
    aliyun = host in ('dashscope.aliyuncs.com', 'dashscope-intl.aliyuncs.com', 'dashscope-us.aliyuncs.com', 'cn-hongkong.dashscope.aliyuncs.com', 'token-plan.cn-beijing.maas.aliyuncs.com') or bool(re.fullmatch(r'[a-zA-Z0-9-]+\.(cn-beijing|ap-northeast-1|eu-central-1|us-east-1)\.maas\.aliyuncs\.com', host))
    hybrid_deepseek = bool(re.fullmatch(r'deepseek-v(?:3\.[12](?:-exp)?|4(?:\.1)?-(?:pro|flash)(?:-\d{4})?)', model))
    toggle = None
    # https://help.aliyun.com/zh/model-studio/deep-thinking
    if reasoning and aliyun and model in ('deepseek-v4.1-flash', 'deepseek-v4-flash-0731', 'deepseek-v4-pro-0813'):
        # Planning and report fact comparisons retain bounded reasoning.
        # Simple authorization/presentation checks use the faster mode below.
        toggle = {'enable_thinking': True, 'reasoning_effort': 'low'}
    elif reasoning:
        return config
    elif aliyun and hybrid_deepseek:
        toggle = {'enable_thinking': False}
    # https://api-docs.deepseek.com/guides/thinking_mode/
    elif host == 'api.deepseek.com' and (model == 'deepseek-chat' or hybrid_deepseek):
        toggle = {'thinking': {'type': 'disabled'}}
    if toggle is None:
        return config
    options = {key: value for key, value in config.get('parameters', {}).items() if key not in ('enable_thinking', 'thinking', 'thinking_budget', 'reasoning_effort')}
    return {**config, 'parameters': {**options, **toggle}}


def business_model_config(config, choice):
    """Default known hybrid models to bounded tool execution, respecting presets.

    Explicit reasoning settings and unknown providers keep their own behavior.
    Only the assistant planner uses this default; report generation is unchanged.
    """
    if choice.get('presetId') or any(key in config.get('parameters', {}) for key in ('enable_thinking', 'thinking', 'thinking_budget', 'reasoning_effort')):
        return config
    candidate = reply_review_config(config, reasoning=True)
    return candidate if candidate.get('parameters', {}).get('reasoning_effort') == 'low' else config
