"""Bounded metadata-only correlated timings; never log prompts or model text."""
import json
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar

log = logging.getLogger('paa.latency')
ALLOWED = frozenset({'call', 'kind', 'reason', 'generation', 'seq', 'bytes', 'input_tokens', 'output_tokens', 'state', 'error', 'elapsed_ms'})


class Timing:
    def __init__(self, job, attempt=0, fence=0, *, clock=time.monotonic):
        self.identity = {'job': job, 'attempt': attempt, 'fence': fence}
        self.clock, self.started = clock, clock()
        self.count = 0
        self.repeated = {}

    def mark(self, event, **fields):
        if event.startswith(('publish.', 'source_check.')) or event == 'sse.send':
            self.repeated[event] = self.repeated.get(event, 0) + 1
            # Sample hot-path spans in pairs, leaving room for model completion
            # and final persistence even for very long answers.
            if self.repeated[event] > 32:
                return
        if self.count >= 512:
            return
        self.count += 1
        value = {**self.identity, 'event': event, 'at_ms': round((self.clock() - self.started) * 1000, 3),
                 **{key: value for key, value in fields.items() if key in ALLOWED}}
        log.info('latency %s', json.dumps(value, separators=(',', ':')))
        return value

    @contextmanager
    def span(self, event, **fields):
        at = self.clock()
        self.mark(event + '.start', **fields)
        try:
            yield
        finally:
            self.mark(event + '.end', elapsed_ms=round((self.clock() - at) * 1000, 3), **fields)


call_kind = ContextVar('model_call_kind', default=None)
