from .types import Policy


def retry_delay(failure, count, *, policy=Policy(), jitter=lambda: 0):
    if not failure.retryable or count >= policy.max_attempts:
        return None
    if failure.retry_after is not None:
        return max(0, failure.retry_after)
    return policy.delays[min(count - 1, len(policy.delays) - 1)] + max(0, jitter())
