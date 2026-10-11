"""Real Redis; process-local substitutes cannot satisfy these tests."""
import asyncio
import json
import os
import sys
from uuid import uuid4
import pytest
import pytest_asyncio
from app.tasks.streaming.protocol import Identity, MAX_EVENTS, MAX_SNAPSHOT_BYTES
from app.tasks.streaming.redis_store import RedisReplyStore, StreamUnavailable
from _support.agent.reply_stream_transport import value, test_real_capacity_refusal_and_redis_restart as real_capacity_refusal_and_redis_restart

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def store():
    url = os.getenv('PAA_REPLY_STREAM_TEST_URL')
    if not url:
        pytest.skip('PAA_REPLY_STREAM_TEST_URL must target an isolated real Redis')
    value = RedisReplyStore(url, namespace='spec055:test:' + uuid4().hex)
    await value.client.ping()
    yield value
    keys = [key async for key in value.client.scan_iter(match=value.namespace + ':*')]
    if keys:
        await value.client.delete(*keys)
    await value.close()



async def test_atomic_snapshot_handoff_trimmed_cursor_and_foreign_identities(store):
    identity = Identity('company', 'owner', 'job', 1, 2)
    for seq in range(1, 310):
        current = value(identity, seq, '中' * seq)
        await store.publish(identity, current, {**identity.public(), 'generation': 1, 'seq': seq, 'type': 'delta', 'delta': '中'})
    snapshot = await store.snapshot(identity)
    assert snapshot['seq'] == 309 and snapshot['text'] == '中' * 309
    rows = await store.read(identity, '0-0')
    assert rows[0][1]['seq'] > 1  # Detect the gap, recover via snapshot cursor.
    assert await store.client.xlen(store.keys(identity)[1]) <= MAX_EVENTS
    assert await store.snapshot(Identity('company', 'peer', 'job', 1, 2)) is None
    assert not await store.publish(identity, value(identity, 308, 'out-of-order'), {'seq': 308})
    assert not await store.publish(identity, value(identity, 309, 'duplicate'), {'seq': 309})
    await store.publish(identity, value(identity, 1, 'new', generation=2), {'seq': 1, 'type': 'sync'})
    assert not await store.publish(identity, value(identity, 999, 'old generation'), {'seq': 999})
    assert (await store.snapshot(identity))['text'] == 'new'
    await store.seal(identity, closed=False, generation=1)
    assert (await store.snapshot(identity))['text'] == 'new'
    await store.seal(identity)
    await store.seal(identity, closed=False, generation=2)
    assert not await store.publish(identity, value(identity, 2, 'late', generation=2), {'seq': 2})
    assert (await store.snapshot(identity))['text'] == ''
    assert not await store.publish(identity, value(identity, 1, 'late generation', generation=900), {'seq': 1})
    empty = Identity('company', 'owner', 'empty-cancel', 1, 2)
    await store.seal(empty)
    assert not await store.publish(empty, value(empty, 1, 'first late token'), {'seq': 1})


async def test_byte_budget_ttl_and_client_restart(store):
    identity = Identity('company', 'owner', 'long', 0, 1)
    for seq in range(1, 50):
        await store.publish(identity, value(identity, seq, '汉' * 100_000), {'seq': seq, 'delta': '汉' * 20_000})
    keys = store.keys(identity)
    sizes = await asyncio.gather(*(store.client.memory_usage(key) for key in keys))
    assert sum(size or 0 for size in sizes) <= 1024 * 1024
    assert 0 < await store.client.ttl(keys[0]) <= 900
    with pytest.raises(StreamUnavailable, match='capacity'):
        await store.publish(identity, value(identity, 99, 'a' * MAX_SNAPSHOT_BYTES), {'seq': 99})
    with pytest.raises(StreamUnavailable, match='capacity'):
        await store.publish(identity, value(identity, 99, 'safe'), {'seq': 99, 'delta': 'a' * (64 * 1024)})
    slash = Identity('company', 'owner', 'slash-budget', 0, 1)
    await store.publish(slash, value(slash, 1, '/' * (MAX_SNAPSHOT_BYTES - 1024)), {'seq': 1})
    assert len((await store.client.get(store.keys(slash)[0])).encode()) <= MAX_SNAPSHOT_BYTES
    reader = RedisReplyStore(os.environ['PAA_REPLY_STREAM_TEST_URL'], namespace=store.namespace)
    assert (await reader.snapshot(identity))['seq'] == 49
    await reader.close()
    for key in keys:
        await store.client.pexpire(key, 30)
    await asyncio.sleep(.04)
    assert await store.snapshot(identity) is None


async def test_two_independent_reader_processes_receive_worker_process_snapshot(store):
    identity = Identity('company', 'owner', 'processes', 1, 1)
    source = '''
import asyncio, json, os
from app.tasks.streaming.redis_store import RedisReplyStore
from app.tasks.streaming.protocol import Identity
async def main():
 s=RedisReplyStore(os.environ['PAA_REPLY_STREAM_TEST_URL'], namespace=os.environ['TEST_STREAM_NAMESPACE'])
 i=Identity('company','owner','processes',1,1)
 if os.environ['TEST_STREAM_ROLE']=='writer':
  await s.publish(i, {**i.public(),'generation':1,'seq':1,'text':'跨进程😀','callId':'call','source':{},'state':'streaming'}, {'type':'sync','generation':1,'seq':1})
 else:
  v=await s.snapshot(i)
  print(json.dumps({'text':v['text'],'seq':v['seq'],'cursor':v['cursor']},ensure_ascii=False))
 await s.close()
asyncio.run(main())
'''
    async def process(role):
        env = {**os.environ, 'TEST_STREAM_NAMESPACE': store.namespace, 'TEST_STREAM_ROLE': role}
        child = await asyncio.create_subprocess_exec(sys.executable, '-c', source, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await child.communicate()
        assert child.returncode == 0, stderr.decode()
        return json.loads(stdout) if stdout else None
    await process('writer')
    first, second = await asyncio.gather(process('api1'), process('api2'))
    assert first == second and first['text'] == '跨进程😀' and first['seq'] == 1


async def test_real_capacity_refusal_and_redis_restart():
    await real_capacity_refusal_and_redis_restart()
