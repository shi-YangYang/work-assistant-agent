"""Single source of limits; each execution persists its own immutable policy."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Policy:
    version: str = 'assistant-v1'
    seconds: int = 1800
    tools: int = 64
    models: int = 96
    warn_tools: int = 8
    warn_models: int = 12
    warn_seconds: int = 180
    reserve_models: int = 3
    reserve_seconds: int = 120

    @property
    def graph_steps(self):
        # Before/after middleware, model and tool supersteps per model request,
        # including discoveries and the final prose/protocol correction.
        return 8 * self.models + 16

    @property
    def nodes(self):
        # One tool plus up to three child application nodes per admitted tool;
        # one durable node per model call; 32 prior-scope recovery summaries.
        return 4 * self.tools + self.models + 32

    def dump(self):
        return asdict(self)


DEFAULT = Policy()
LEGACY = Policy(version='assistant-legacy', seconds=420, tools=16, models=32,
                warn_tools=2, warn_models=3, warn_seconds=60, reserve_seconds=0)
