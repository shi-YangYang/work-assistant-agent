"""One tool call, sequential images, with the existing per-image recovery receipts."""
from collections import Counter
from app.integrations.models.transport import ProviderError
from app.modules.image_generation.service import generate, validate_input
from app.tasks.feedback.image_feedback import register, advance


def requests(prompt, count, prompts, title, operation):
    if type(count) is not int or not 1 <= count <= 4:
        raise ProviderError('image_input', '每条消息最多生成 4 张图片，请指定 1～4 张。', sent=False)
    if prompts is not None:
        if not isinstance(prompts, list) or not 1 <= len(prompts) <= 4 or prompt or count not in (1, len(prompts)):
            raise ProviderError('image_input', '请使用一段描述和张数，或提供 1～4 段图片描述，不要同时使用两种方式。', sent=False)
        # A matching count is redundant, not another batch multiplier. Keep the
        # original list and per-image slots so either spelling has one receipt.
        values = prompts
    else:
        values = [prompt] * count
    # Validate the whole request before the first provider call. Slots remain
    # stable on restart and cannot exceed the per-message image allowance.
    validate_input(values[0], title, operation)
    for index, value in enumerate(values):
        validate_input(value, title, operation + index)
    return values


def summary(results, requested):
    completed = sum(result.get('imageCount', 0) for result in results if result.get('state') == 'succeeded')
    pending = next((result['state'] for result in results if result.get('state') in ('retryable', 'unknown', 'running')), None)
    state = pending or ('succeeded' if all(result.get('state') == 'succeeded' for result in results) else 'partial' if completed else 'failed')
    return {'state': state, 'requestedCount': requested, 'imageCount': completed,
            'notExecutedCount': requested - len(results), 'results': results,
            'message': f'已生成 {completed}/{requested} 张图片。' + ('成功图片已保存，重试会复用已有结果。' if state != 'succeeded' else '')}


async def generate_batch(context, *, prompt='', count=1, prompts=None, title='生成图片', operation=1, **dimensions):
    values = requests(prompt, count, prompts, title, operation)
    async with context.image_generation_lock:
        results, variants = [], Counter()
        operations = list(range(operation, operation + len(values)))
        await register(context, operations)
        for index, value in enumerate(values):
            normalized = ' '.join(value.split())
            # Explicit variants are distinct images; replaying the same batch
            # uses the same ordinal and therefore the same durable receipt.
            try:
                result = await generate(context, prompt=value, title=title, operation=operation + index,
                                        variant=variants[normalized], **dimensions)
            except ProviderError as error:
                # Input/configuration failures happen before a durable claim.
                # Keep earlier deliveries in the batch response and stop here.
                result = {'state': 'failed', 'code': error.code, 'message': str(error)}
                results.append(result)
                await advance(context, operation + index, result, operations[index + 1:], stop=True)
                break
            variants[normalized] += 1
            results.append(result)
            stop = result.get('state') in ('retryable', 'unknown', 'running', 'conflict', 'cancelled')
            await advance(context, operation + index, result, operations[index + 1:], stop=stop)
            if stop:
                break
        return results[0] if len(values) == 1 else summary(results, len(values))
