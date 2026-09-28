"""Provider-scoped context capacities; unknown compatible aliases stay unknown."""
from urllib.parse import urlsplit

UNKNOWN = {'contextWindow': None, 'inputLimit': None, 'maxOutput': None, 'source': 'unknown'}


def capability(base_url, model, override=None):
    host = (urlsplit(base_url).hostname or '').lower()
    result = dict(UNKNOWN)
    aliyun = host in {'dashscope.aliyuncs.com', 'dashscope-intl.aliyuncs.com', 'dashscope-us.aliyuncs.com', 'token-plan.cn-beijing.maas.aliyuncs.com'} or host.endswith('.maas.aliyuncs.com')
    # Official Model Studio specifications distinguish native and Vanchin entries.
    if aliyun and model == 'deepseek-v4.1-flash':
        result = {'contextWindow': 1000000, 'inputLimit': 1000000, 'maxOutput': 393216, 'source': 'official:aliyun/deepseek-v4.1-flash'}
    elif aliyun and model == 'vanchin/deepseek-v4.1-flash':
        result = {'contextWindow': 1048576, 'inputLimit': 1048576, 'maxOutput': 393216, 'source': 'official:aliyun/vanchin-deepseek-v4.1-flash'}
    elif host == 'api.deepseek.com' and model in {'deepseek-v4.1-flash', 'deepseek-flash'}:
        result = {'contextWindow': 1000000, 'inputLimit': 1000000, 'maxOutput': 393216, 'source': 'official:deepseek/v4.1-flash'}
    elif host == 'api.openai.com' and model in {'gpt-4.1', 'gpt-4.1-mini', 'gpt-4.1-nano', 'gpt-4.1-2025-04-14', 'gpt-4.1-mini-2025-04-14', 'gpt-4.1-nano-2025-04-14'}:
        result = {'contextWindow': 1047576, 'inputLimit': None, 'maxOutput': 32768, 'source': 'official:openai/gpt-4.1'}
    elif host == 'api.openai.com' and model in {'gpt-4o', 'gpt-4o-mini', 'gpt-4o-2024-08-06', 'gpt-4o-mini-2024-07-18'}:
        result = {'contextWindow': 128000, 'inputLimit': None, 'maxOutput': 16384, 'source': 'official:openai/gpt-4o'}
    if isinstance(override, int) and not isinstance(override, bool) and 0 < override <= 10000000:
        result = {**result, 'contextWindow': override, 'source': 'override'}
    return result
