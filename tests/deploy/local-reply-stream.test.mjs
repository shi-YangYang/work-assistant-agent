import assert from 'node:assert/strict'
import test from 'node:test'
import {
  replyStreamConfig,
  startLocalReplyStream,
} from '../../scripts/company/reply-stream-local.mjs'

test('external Redis variants do not execute Docker commands or acquire a local owner', async () => {
  for (const url of [
    'redis://127.0.0.1:16379/0',
    'rediss://redis.example/0',
    'redis://user:private@localhost:6379/0',
  ]) {
    const value = await startLocalReplyStream({
      infra: { values: { PAA_REPLY_STREAM_REDIS_URL: url } },
    })
    assert.equal(value.url, url)
    await value.stop()
  }
})

test('local Redis uses the shared Compose lifecycle and carries the effective URL', async () => {
  const calls = []
  const infra = {
    project: 'isolated',
    values: {
      PAA_REPLY_STREAM_REDIS_URL: 'redis://127.0.0.1:16397/0',
      PAA_LOCAL_REDIS_PORT: '16397',
    },
  }
  const value = await startLocalReplyStream({
    infra,
    lifecycle: { start: async (...args) => calls.push(args) },
  })
  assert.deepEqual(calls, [['redis', 30]])
  assert.equal(value.url, 'redis://127.0.0.1:16397/0')
  assert.equal(replyStreamConfig({}).local, true)
  await value.stop()
})
