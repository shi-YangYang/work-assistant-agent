"""Shared controlled fixtures extracted from test_reply_stream_transport."""
import asyncio
import os
from uuid import uuid4
import pytest
from app.tasks.streaming.protocol import Identity
from app.tasks.streaming.redis_store import RedisReplyStore, StreamUnavailable




def value(identity, seq, text, generation=1):
    return {**identity.public(), 'generation': generation, 'seq': seq, 'text': text,
            'callId': 'call', 'source': {}, 'state': 'streaming'}


async def test_real_capacity_refusal_and_redis_restart():
    url = os.getenv('PAA_REPLY_STREAM_FAULT_URL')
    container = os.getenv('PAA_REPLY_STREAM_FAULT_CONTAINER')
    if not url:
        pytest.skip('Fault Redis must be explicitly isolated from other runs')
    store = RedisReplyStore(url, namespace='spec055:fault:' + uuid4().hex)
    identity = Identity('fault', 'owner', 'job', 0, 1)
    try:
        await store.client.config_set('maxmemory', 1)
        with pytest.raises(StreamUnavailable):
            await store.publish(identity, value(identity, 1, 'text'), {'seq': 1})
        await store.client.config_set('maxmemory', 64 * 1024 * 1024)
        await store.publish(identity, value(identity, 1, 'text'), {'seq': 1})
        if container:
            assert container == 'noria-spec055-redis-fault'
            child = await asyncio.create_subprocess_exec('docker', 'restart', container, stdout=asyncio.subprocess.DEVNULL)
            assert await child.wait() == 0
            for _ in range(20):
                try:
                    await store.client.ping()
                    break
                except Exception:
                    await asyncio.sleep(.1)
            assert await store.snapshot(identity) is None
    finally:
        await store.client.config_set('maxmemory', 64 * 1024 * 1024)
        await store.client.delete(*store.keys(identity))
        await store.close()
