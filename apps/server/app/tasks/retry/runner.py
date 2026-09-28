import asyncio
import time
from .policy import retry_delay
from .types import Attempt, Failure, NodeFailed, Policy


async def run(operation, *, classify, before, emit, attempt=None, deadline=None,
              clock=time.time, wait=asyncio.sleep, jitter=lambda: 0, policy=Policy(), recover=None):
    """One retry owner. Persist 'running' before IO, and waiting before sleeping.

    before is also called during waits so leases, cancellation and authorization
    are checked without holding a transaction open. A restored running attempt
    was already counted by its owner; callers classify that interruption first.
    recover optionally returns (found, result) from an authorized durable receipt;
    reading a committed result is not another attempt and precedes its budget.
    """
    attempt = attempt or Attempt()
    while True:
        if recover:
            found, result = await recover()
            if found:
                return result
        await before()
        if deadline is not None and clock() >= deadline:
            failure = Failure('deadline', '本次处理已达到时间限制，已停止；可重试此步骤')
            await emit('failed', attempt, failure)
            raise NodeFailed(failure)
        if attempt.next_at is not None:
            while clock() < attempt.next_at:
                await before()
                remaining = min(attempt.next_at, deadline or float('inf')) - clock()
                if remaining <= 0:
                    break
                await wait(min(remaining, 1))
            attempt.next_at = None
            continue
        if attempt.count >= policy.max_attempts:
            failure = Failure('exhausted', '此步骤已用完 3 次自动重试，可重试此步骤')
            await emit('failed', attempt, failure)
            raise NodeFailed(failure)
        attempt.count += 1
        await emit('running', attempt, None)
        try:
            result = await operation()
        except asyncio.CancelledError:
            await emit('cancelled', attempt, Failure('cancelled', '处理已取消', cancelled=True))
            raise
        except Exception as error:
            # Delivery may fail after the side effect committed, including on
            # the last attempt. Resolve that outcome before declaring failure.
            if recover:
                found, result = await recover()
                if found:
                    return result
            failure = classify(error)
            delay = retry_delay(failure, attempt.count, policy=policy, jitter=jitter)
            if delay is None or deadline is not None and clock() + delay >= deadline:
                if delay is not None:
                    failure = Failure('deadline', '剩余处理时间不足，已停止自动重试；可重试此步骤')
                await emit('cancelled' if failure.cancelled else 'failed', attempt, failure)
                if isinstance(error, NodeFailed):
                    raise
                raise NodeFailed(failure) from error
            attempt.next_at = clock() + delay
            await emit('retry_wait', attempt, failure)
        else:
            return result
