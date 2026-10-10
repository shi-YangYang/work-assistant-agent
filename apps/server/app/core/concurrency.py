"""Bounded independent IO; preserve input order and await cancellation cleanup."""
import asyncio


async def map_limited(values, operation, *, concurrency=2):
    items = list(values)
    results = [None] * len(items)
    pending = iter(enumerate(items))

    async def worker():
        for index, value in pending:
            results[index] = await operation(value)

    tasks = [asyncio.create_task(worker()) for _ in range(min(concurrency, len(items)))]
    try:
        await asyncio.gather(*tasks)
        return results
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
