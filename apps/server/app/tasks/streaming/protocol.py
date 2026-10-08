from dataclasses import dataclass

MAX_SNAPSHOT_BYTES = 480 * 1024
MAX_EVENT_BYTES = 64 * 1024
MAX_STREAM_BYTES = 480 * 1024
MAX_EVENTS = 256
TTL_SECONDS = 900


@dataclass(frozen=True)
class Identity:
    company: str
    owner: str
    job: str
    attempt: int
    fence: int

    @property
    def key(self):
        return ':'.join(map(str, (self.company, self.owner, self.job, self.attempt, self.fence)))

    def public(self):
        return {'jobId': self.job, 'attempt': self.attempt, 'fence': self.fence}
