import asyncio
import re
import time
from app.integrations.models import transport
from app.integrations.models.transport import ProviderError, normalize_url, status_error
from urllib.parse import urlsplit


async def catalog(settings, base_url, key):
    base_url = normalize_url(base_url, settings)
    parsed = urlsplit(base_url)
    # Token Plan shares the workspace hostname pattern, but exposes the OpenAI
    # catalog at the configured base URL instead of DashScope's /api/v1/models.
    official = parsed.hostname != 'token-plan.cn-beijing.maas.aliyuncs.com' and (parsed.hostname in ('dashscope.aliyuncs.com', 'dashscope-intl.aliyuncs.com', 'dashscope-us.aliyuncs.com', 'cn-hongkong.dashscope.aliyuncs.com') or bool(re.fullmatch(r'[a-zA-Z0-9-]+\.(cn-beijing|ap-northeast-1|eu-central-1|us-east-1)\.maas\.aliyuncs\.com', parsed.hostname or '')))
    endpoint = f'{parsed.scheme}://{parsed.netloc}/api/v1/models' if official else base_url + '/models'
    ids, size, deadline = [], 0, time.monotonic() + 30
    async with transport.client(settings) as http:
        for page in range(1, 21):
            response = await asyncio.wait_for(http.get(endpoint, params={'page_no': page, 'page_size': 100} if official else None, headers={'Authorization': f'Bearer {key}'}), max(0.01, deadline - time.monotonic()))
            status_error(response)
            size += len(response.content)
            if size > 2 * 1024 * 1024:
                raise ProviderError('limit', '模型目录超过 2 MiB，请手动填写模型 ID')
            data = response.json()
            entries = data.get('output', {}).get('models') if official else data.get('data')
            if not isinstance(entries, list) or len(entries) > 2000:
                raise ProviderError('invalid_response', '模型目录格式无效或超过 2000 项，请手动填写模型 ID')
            field = 'model' if official else 'id'
            ids.extend(x[field] for x in entries if isinstance(x, dict) and isinstance(x.get(field), str) and 0 < len(x[field]) <= 200 and all(ord(c) >= 32 for c in x[field]))
            ids = list(dict.fromkeys(ids))
            if len(ids) > 2000:
                raise ProviderError('limit', '模型目录超过 2000 项，请手动填写模型 ID')
            if not official or len(entries) < 100:
                return {'models': ids, 'source': endpoint, 'truncated': bool(data.get('has_more'))}
    raise ProviderError('limit', '模型目录超过分页上限，请手动填写模型 ID')
