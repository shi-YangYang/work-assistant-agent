"""Retry contracts, independent of providers, persistence and application code."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Failure:
    code: str
    message: str
    retryable: bool = False
    retry_after: float | None = None
    cancelled: bool = False


@dataclass(frozen=True)
class Policy:
    max_attempts: int = 4
    delays: tuple[float, ...] = (1, 2, 4)


@dataclass
class Attempt:
    count: int = 0
    next_at: float | None = None


class NodeFailed(RuntimeError):
    """A child already spent its retry budget; ancestors must not retry it."""
    def __init__(self, failure, node_id=''):
        super().__init__(failure.message)
        self.failure, self.node_id = failure, node_id
