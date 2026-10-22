"""One managed, coalescing publisher per model call. Producer never waits on IO."""
import asyncio
import json
from app.tasks.streaming.protocol import Identity, MAX_SNAPSHOT_BYTES, MAX_EVENT_BYTES
from app.tasks.streaming.redis_store import StreamUnavailable, store_for


class ReplyPublisher:
    def __init__(self, context, call_id):
        self.context, self.call_id = context, call_id
        self.store = store_for(context.settings)
        self.generation = 0
        self.seq = 0
        self.text = ''
        self.source = {}
        self.pending = None
        self.wake = asyncio.Event()
        self.task = None
        self.closed = False
        self.error = None
        self.disabled = False
        self.first = False
        self.authorized_first = False
        self.busy = False
        self.identity = None

    async def start(self):
        for previous in self.context.reply_publishers:
            await previous.close()
            previous.text, previous.pending, previous.source = '', None, {}
        self.context.reply_publishers.clear()
        from app.tasks.lease import lease
        from app.tasks.feedback.feedback_state import update_feedback
        from app.tasks.streaming.lifecycle import source_snapshot
        async with self.context.sessions.begin() as db:
            job, _ = await lease(db, self.context)
            old = (job.feedback or {}).get('replyStream', {})
            self.generation = old.get('generation', 0) + 1
            self.identity = Identity(job.company_id, job.owner_id, job.id, job.attempt, job.fence)
            self.source = source_snapshot(self.context, job)
            # Only identity/control metadata is durable while generation runs.
            job.feedback = {**(job.feedback or {}), 'replyStreamCall': self.call_id,
                            'replyStreamSource': self.source,
                            'replyStream': {'version': 2, 'generation': self.generation, 'state': 'streaming', 'text': ''}}
            update_feedback(job)
        self.context.reply_publishers.append(self)
        self.task = asyncio.create_task(self._run(), name=f'reply:{self.call_id}')

    def mark(self, event, **fields):
        if getattr(self.context, 'timing', None):
            self.context.timing.mark(event, call=self.call_id, generation=self.generation, **fields)

    async def write(self, text, *, state='streaming', force=False):
        if self.error:
            raise self.error
        if self.disabled or self.closed:
            return
        if not self.first and text:
            self.mark('model.first_candidate')
            self.first = True
        # One latest candidate, no token tasks/queue. Final model output remains
        # uncapped in the model adapter; only disposable preview is bounded.
        if len(text.encode()) > MAX_SNAPSHOT_BYTES - 16384:
            self.disabled = True
            self.pending = ('', 'unavailable')
        else:
            self.pending = (text, state)
        self.wake.set()

    async def _run(self):
        try:
            while True:
                await self.wake.wait()
                self.wake.clear()
                # Coalesce bursts, without holding a DB transaction or upstream.
                await asyncio.sleep(.04)
                value, self.pending = self.pending, None
                if value is not None:
                    self.busy = True
                    try:
                        await self._publish(*value)
                    finally:
                        self.busy = False
        except asyncio.CancelledError:
            raise
        except StreamUnavailable:
            self.disabled = True
            await self._unavailable()
        except Exception as error:
            self.error = error
            try:
                await self.store.seal(self.identity)
            except StreamUnavailable:
                pass

    async def _unavailable(self):
        from app.tasks.lease import lease
        from app.tasks.feedback.feedback_state import update_feedback
        try:
            async with self.context.sessions.begin() as db:
                job, _ = await lease(db, self.context)
                if job.feedback.get('replyStreamCall') == self.call_id:
                    job.feedback = {**job.feedback, 'replyStream': {'version': 2, 'generation': self.generation, 'state': 'unavailable', 'text': ''}}
                    update_feedback(job)
        except Exception:
            # Lease/source revocation is handled by the task owner; never retain.
            self.text = ''

    async def _publish(self, text, state):
        from app.tasks.lease import lease
        from app.tasks.streaming.lifecycle import source_snapshot, validate_sources, presentation_text
        from app.modules.messages.models import Message
        self.mark('source_check.start')
        async with self.context.sessions() as db:
            job, actor = await lease(db, self.context)
            if job.feedback.get('replyStreamCall') != self.call_id:
                return
            message = await db.get(Message, job.target_id)
            from app.tasks.feedback.public import prose
            from app.modules.messages.input.input_text import request_text
            text = prose(text, job, request_text(message, job), complete=state != 'streaming')
            source = source_snapshot(self.context, job)
            team = await validate_sources(db, actor, job, message, source)
            if team or job.access.get('team') or message.access.get('team'):
                text, state = '', 'withdrawn'
        self.mark('source_check.end')
        if text and not self.authorized_first:
            self.mark('model.first_answer')
            self.authorized_first = True
        text = presentation_text(text)
        if text == self.text and state == 'streaming':
            return
        self.seq += 1
        identity = {**self.identity.public(), 'generation': self.generation, 'seq': self.seq, 'callId': self.call_id}
        delta = text[len(self.text):] if text.startswith(self.text) else None
        kind = 'delta' if delta is not None and len(delta.encode()) <= MAX_EVENT_BYTES and self.seq > 1 else 'sync'
        if state in ('withdrawn', 'unavailable'):
            kind = state
        event = {**identity, 'type': kind, 'state': state}
        if kind == 'delta':
            event['delta'] = delta
            if len(json.dumps(event, ensure_ascii=False).encode()) > MAX_EVENT_BYTES:
                event = {**identity, 'type': 'sync', 'state': state}
        value = {**identity, 'text': text, 'state': state, 'source': source}
        self.mark('publish.start', seq=self.seq, bytes=len(text.encode()))
        accepted = await self.store.publish(self.identity, value, event)
        if not accepted:
            from app.tasks.context import LostLease
            raise LostLease()
        self.mark('publish.end', seq=self.seq)
        self.text, self.source = text, source
        if state == 'unavailable':
            await self._unavailable()

    async def drain(self):
        while self.task and not self.task.done() and (self.pending is not None or self.wake.is_set() or self.busy):
            await asyncio.sleep(.01)
        if self.error:
            raise self.error

    async def flush(self):
        await self.drain()
        await self.close()

    async def withdraw(self):
        self.closed = True
        self.pending = None
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.text = ''
        if self.identity:
            try:
                await self.store.seal(self.identity, closed=False, generation=self.generation)
            except StreamUnavailable:
                pass

    async def fail(self, error, text=None):
        from app.tasks.streaming.lifecycle import failure_state
        if failure_state(error) == 'interrupted':
            await self.write(self.text if text is None else text, state='interrupted', force=True)
            try:
                await self.flush()
            except Exception:
                await self.withdraw()
        else:
            await self.withdraw()

    async def close(self):
        self.closed = True
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
