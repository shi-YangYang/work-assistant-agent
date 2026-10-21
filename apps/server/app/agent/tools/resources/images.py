import json
from fastapi import HTTPException
from app.agent.tool_results import http_failure
from langchain.tools import ToolRuntime, tool
from app.integrations.models.transport import ProviderError
from app.modules.image_generation.batch import generate_batch
from app.tasks.context import RunContext


@tool
async def generate_image(runtime: ToolRuntime[RunContext], prompt: str = '', title: str = '生成图片', operation: int = 1,
                         width: int | None = None, height: int | None = None, aspect: str = '', resolution: str = '', use: str = '',
                         count: int = 1, prompts: list[str] | None = None) -> str:
    """Generate private pictures only when requested, not edits, analysis or charts.
    For N images, make ONE call: prompt + count=N for variants, or prompts=[...]
    for N distinct pictures. Never split one batch into parallel single-image
    calls. The server queues them sequentially; max 4 images per message.
    operation is the first slot (1-4), default 1; a batch uses consecutive slots.
    Retry identical arguments to reuse saved images, never drift prompts or sizes.
    Explicit width/height win over aspect (16:9) or resolution (1K/2K/4K).
    use: avatar/icon/cover/desktop_wallpaper/phone_wallpaper/poster. Leave omitted
    sizes empty; the configured model supplies defaults. Clarify unsupported or
    conflicting sizes. Return real private files, not provider URLs.
    """
    try:
        result = await generate_batch(runtime.context, prompt=prompt, title=title, operation=operation,
            width=width, height=height, aspect=aspect, resolution=resolution, use=use, count=count, prompts=prompts)
    except ProviderError as error:
        result = {'state': 'failed', 'code': error.code, 'message': str(error)}
    except HTTPException as error:
        result = http_failure(error)
    if result.get('state') == 'retryable':
        # Retry the durable operation, never a fresh provider creation. The
        # harness bounds attempts and exposes its existing retry status.
        raise ProviderError('network', result['message'])
    return json.dumps(result, ensure_ascii=False)
