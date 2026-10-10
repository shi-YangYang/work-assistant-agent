import re
from app.modules.model_services.schemas import parameters
from urllib.parse import urlsplit


def request_options(model, effort=None):
    from app.modules.model_services.reasoning.policy import effort_options
    from app.modules.model_services.reasoning.legacy import direct_model
    if 'legacyParameters' in model:
        return parameters(model['legacyParameters'])
    model = direct_model(model)
    selected = model.get('reasoning', {}).get('initial') if effort is None else effort
    return parameters(effort_options(model, selected) if selected else model.get('parameters', model.get('legacyParameters', {})))


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
    if reasoning:
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
    """The accepted effort owns assistant reasoning; omitted settings use provider defaults."""
    return config


def report_model_config(config, choice):
    """Reserve bounded report output for its JSON unless reasoning was selected."""
    options = config.get('parameters', {})
    nested = options.get('reasoning')
    if choice.get('effort') or choice.get('explicitReasoning') or choice.get('presetId') or any(key in options for key in ('enable_thinking', 'thinking', 'thinking_budget', 'reasoning_effort')) or (isinstance(nested, dict) and 'effort' in nested):
        return config
    return reply_review_config(config)
