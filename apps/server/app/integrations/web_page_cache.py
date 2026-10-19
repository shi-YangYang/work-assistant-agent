"""Run-local successful public page snapshots; no credentials or business data."""
import asyncio
import json
import time
from collections import OrderedDict


class WebPageCache:
    def __init__(self, *, max_pages=8, max_bytes=8 * 1024 * 1024, ttl=120, clock=time.monotonic):
        self.max_pages, self.max_bytes, self.ttl, self.clock = max_pages, max_bytes, ttl, clock
        self.pages, self.pending = OrderedDict(), {}
        self.bytes = 0

    async def get(self, key, download, *, refresh=False):
        instant = self.clock()
        for old, (at, value, size) in list(self.pages.items()):
            if instant - at >= self.ttl:
                self.pages.pop(old)
                self.bytes -= size
        if key in self.pages and not refresh:
            self.pages.move_to_end(key)
            return self.pages[key][1], True
        if key in self.pending:
            return await asyncio.shield(self.pending[key]), True
        async def fetch():
            try:
                value = await download()
                size = len(json.dumps(value, ensure_ascii=False).encode()) + len(key.encode())
                # A failed refresh must not discard still-valid source text.
                # Replace it only after a successful download, even if the new
                # page is too large to retain.
                previous = self.pages.pop(key, None)
                if previous:
                    self.bytes -= previous[2]
                if size <= self.max_bytes:
                    while self.pages and (len(self.pages) >= self.max_pages or self.bytes + size > self.max_bytes):
                        _, (_, _, removed) = self.pages.popitem(last=False)
                        self.bytes -= removed
                    self.pages[key] = (self.clock(), value, size)
                    self.bytes += size
                return value
            finally:
                self.pending.pop(key, None)
        task = self.pending[key] = asyncio.create_task(fetch())
        # A caller can be cancelled while a shared download finishes later.
        task.add_done_callback(lambda finished: None if finished.cancelled() else finished.exception())
        return await asyncio.shield(task), False

    async def close(self):
        for task in self.pending.values():
            task.cancel()
        await asyncio.gather(*self.pending.values(), return_exceptions=True)
        self.pending.clear()
        self.pages.clear()
        self.bytes = 0
