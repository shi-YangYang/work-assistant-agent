import { spawn } from 'node:child_process'
import { resolve } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { JsonLineClient } from '../../src/desktop/json-line-client'

const clients: JsonLineClient[] = []
const createClient = (): { client: JsonLineClient; failure: ReturnType<typeof vi.fn> } => {
  const child = spawn(process.execPath, [resolve('tests/desktop/fixture-core.mjs')], {
    stdio: ['pipe', 'pipe', 'pipe'],
  })
  const failure = vi.fn()
  const client = new JsonLineClient(child, failure, 1_000)
  clients.push(client)
  return { client, failure }
}

afterEach(async () => {
  await Promise.all(clients.splice(0).map((client) => client.stop()))
})

describe('JSON Lines process boundary', () => {
  it('associates concurrent out-of-order replies by id', async () => {
    const { client } = createClient()
    const slow = client.request('delayed')
    const fast = client.request('fast')
    expect(await fast).toMatchObject({ method: 'fast' })
    expect(await slow).toMatchObject({ method: 'delayed' })
    expect(client.pendingCount).toBe(0)
  })

  it('handles fragmented UTF-8 and newlines', async () => {
    const { client } = createClient()
    expect(await client.request('split')).toEqual({ method: 'split', text: '中文' })
  })

  it('cleans timed-out requests and ignores their late replies', async () => {
    const { client, failure } = createClient()
    await expect(client.request('delayed', 25)).rejects.toMatchObject({ code: 'timeout' })
    expect(client.pendingCount).toBe(0)
    expect(await client.request('delayed')).toMatchObject({ method: 'delayed' })
    expect(failure).not.toHaveBeenCalled()
    expect(client.pendingCount).toBe(0)
  })

  it.each(['invalid', 'flood', 'both'])('rejects and stops on %s output', async (method) => {
    const { client, failure } = createClient()
    await expect(client.request(method)).rejects.toMatchObject({ code: 'invalid_output' })
    expect(client.pendingCount).toBe(0)
    expect(failure).toHaveBeenCalledOnce()
    await expect(client.request('fast')).rejects.toMatchObject({ code: 'invalid_output' })
  })

  it('does not expose arbitrary error contents', async () => {
    const { client } = createClient()
    await expect(client.request('remote_error')).rejects.toMatchObject({ code: 'remote_error' })
    expect(await client.request('fast')).toMatchObject({ method: 'fast' })
  })

  it('rejects all pending requests after process exit', async () => {
    const { client } = createClient()
    const requests = [client.request('hang'), client.request('exit')]
    const settled = await Promise.allSettled(requests)
    expect(settled.every((result) => result.status === 'rejected')).toBe(true)
    expect(client.pendingCount).toBe(0)
  })

  it('bounds outstanding requests', async () => {
    const { client } = createClient()
    const requests = Array.from({ length: 64 }, () => client.request('hang', 150))
    const settled = Promise.allSettled(requests)
    await expect(client.request('fast')).rejects.toMatchObject({ code: 'busy' })
    await settled
    expect(client.pendingCount).toBe(0)
  })

  it('stops idempotently and rejects pending work', async () => {
    const { client, failure } = createClient()
    const request = client.request('hang').catch((error: unknown) => error)
    await Promise.all([client.stop(), client.stop()])
    expect(await request).toBeInstanceOf(Error)
    expect(client.pendingCount).toBe(0)
    expect(failure).not.toHaveBeenCalled()
  })

  it('reports a missing executable without leaking its path', async () => {
    const child = spawn(resolve('artifacts/nonexistent-python'), [], {
      stdio: ['pipe', 'pipe', 'pipe'],
    })
    const client = new JsonLineClient(child, vi.fn())
    clients.push(client)
    await expect(client.request('health')).rejects.toMatchObject({ code: 'python_missing' })
  })
})
