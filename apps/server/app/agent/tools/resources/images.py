import json
from fastapi import HTTPException
from langchain.tools import ToolRuntime, tool
from app.integrations.models.transport import ProviderError
from app.modules.image_generation.service import generate
from app.tasks.context import RunContext


@tool
async def generate_image(prompt: str, runtime: ToolRuntime[RunContext], title: str = '生成图片', operation: int = 1,
                         width: int | None = None, height: int | None = None, aspect: str = '', resolution: str = '', use: str = '') -> str:
    """Generate ONE private image from text, only when the user requests an actual picture.
    Not image editing, reference-image generation, analysis, charts or prompt writing.
    operation (1-8) stays stable within the message across retries; identical requests
    reuse results even with a new operation. Do not change prompt to bypass a failed receipt.
    Explicit width/height win; aspect e.g.16:9 or resolution e.g.1K/2K/4K.
    use: avatar/icon/cover/desktop_wallpaper/phone_wallpaper/poster. The configured
    image model determines supported sizes and defaults. Unsupported or conflicting
    sizes need user clarification; do not change them to bypass a failure.
    Leave unspecified dimensions empty. Return real private files, not provider URLs.
    """
    try:
        result = await generate(runtime.context, prompt=prompt, title=title, operation=operation,
            width=width, height=height, aspect=aspect, resolution=resolution, use=use)
    except ProviderError as error:
        result = {'state': 'failed', 'code': error.code, 'message': str(error)}
    except HTTPException as error:
        result = {'state': 'conflict' if error.status_code == 409 else 'failed', 'message': error.detail['message']}
    if result.get('state') == 'retryable':
        # Retry the durable operation, never a fresh provider creation. The
        # harness bounds attempts and exposes its existing retry status.
        raise ProviderError('network', result['message'])
    return json.dumps(result, ensure_ascii=False)
