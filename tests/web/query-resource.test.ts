import { afterEach, expect, it, vi } from 'vitest'
import { ApiError, setCsrf } from '../../apps/web/src/api/client'
import { assistantQuery } from '../../apps/web/src/features/assistant/api/queries'
import { QueryResource, clearQueryResources } from '../../apps/web/src/lib/query-resource'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}
afterEach(() => {
  clearQueryResources()
  vi.useRealTimers()
})

it('shares concurrent readers, leaves other subscribers alive and survives immediate remount', async () => {
  vi.useFakeTimers()
  const pending = deferred<{ revision: number }>()
  let signal: AbortSignal | undefined
  const read = vi.fn((current: AbortSignal) => {
    signal = current
    return pending.promise
  })
  const resource = new QueryResource(read)
  const first = resource.subscribe(vi.fn())
  const second = resource.subscribe(vi.fn())
  const controller = new AbortController()
  const cancelled = resource.get(controller.signal).catch((error) => error)
  const kept = resource.get()
  const passive = resource.refresh()
  first()
  controller.abort()
  second()
  const remount = resource.subscribe(vi.fn())
  await vi.advanceTimersByTimeAsync(0)
  expect(read).toHaveBeenCalledTimes(1)
  expect(signal?.aborted).toBe(false)
  pending.resolve({ revision: 1 })
  expect(await kept).toEqual({ revision: 1 })
  expect((await cancelled).name).toBe('AbortError')
  await passive
  expect(read).toHaveBeenCalledTimes(1)
  remount()
  resource.dispose()
})

it('queues exactly one fresh read for writes during an older GET and never exposes that old reply', async () => {
  const old = deferred<{ revision: number }>()
  const read = vi.fn().mockReturnValueOnce(old.promise).mockResolvedValue({ revision: 3 })
  const resource = new QueryResource<{ revision: number }>(read)
  const observed: unknown[] = []
  const stop = resource.subscribe(() => observed.push(resource.getSnapshot().data))
  const initial = resource.ensure()
  await Promise.resolve()
  void resource.refresh()
  void resource.refresh()
  void resource.invalidate()
  void resource.invalidate()
  old.resolve({ revision: 1 })
  await initial
  expect(read).toHaveBeenCalledTimes(2)
  expect(resource.getSnapshot().data).toEqual({ revision: 3 })
  expect(observed).not.toContainEqual({ revision: 1 })
  stop()
  resource.dispose()
})

it('uses a complete mutation response immediately and ignores an older GET without another GET', async () => {
  const old = deferred<{ title: string }>()
  const read = vi.fn(() => old.promise)
  const resource = new QueryResource(read)
  const stop = resource.subscribe(vi.fn())
  const initial = resource.ensure()
  await Promise.resolve()
  resource.set({ title: '新的标题' })
  old.resolve({ title: '旧的标题' })
  await initial
  expect(await resource.get()).toEqual({ title: '新的标题' })
  expect(read).toHaveBeenCalledTimes(1)
  stop()
  resource.dispose()
})

it('separates full query parameters and account scope and rejects late previous-session responses', async () => {
  const old = deferred<string>()
  const first = assistantQuery(
    '/messages?conversationId=a&cursor=one',
    'company:a:employee',
    () => old.promise,
  )!
  expect(assistantQuery('/messages?conversationId=a&cursor=two', 'company:a:employee')).not.toBe(
    first,
  )
  expect(assistantQuery('/messages?conversationId=a&cursor=one', 'company:b:employee')).not.toBe(
    first,
  )
  const pending = first.get().catch((error) => error)
  await Promise.resolve()
  setCsrf('new-session')
  old.resolve('private old text')
  expect((await pending).name).toBe('AbortError')
  expect(first.getSnapshot().data).toBeNull()
  expect(assistantQuery('/messages?conversationId=a&cursor=one', 'company:a:employee')).not.toBe(
    first,
  )
})

it.each([403, 404])(
  'clears protected content on %s and allows one explicit retry',
  async (status) => {
    const read = vi
      .fn()
      .mockResolvedValueOnce('secret')
      .mockRejectedValueOnce(new ApiError(status, 'forbidden', '无权访问'))
      .mockResolvedValue('restored')
    const resource = new QueryResource<string>(read)
    await resource.ensure()
    await resource.refresh()
    expect(resource.getSnapshot().data).toBeNull()
    await resource.ensure()
    expect(read).toHaveBeenCalledTimes(2)
    await resource.refresh()
    expect(resource.getSnapshot().data).toBe('restored')
    resource.dispose()
  },
)

it('does not retry transient failures by timer and obeys Retry-After for manual retries', async () => {
  vi.useFakeTimers()
  const read = vi
    .fn()
    .mockRejectedValueOnce(new ApiError(429, 'limited', '稍后重试', 'rate_limited', null, 60))
    .mockResolvedValue('ok')
  const resource = new QueryResource<string>(read)
  const stop = resource.subscribe(vi.fn())
  await expect(resource.get()).rejects.toThrow('稍后重试')
  await expect(resource.get(undefined, { fresh: true })).rejects.toThrow('稍后重试')
  await vi.advanceTimersByTimeAsync(60000)
  expect(read).toHaveBeenCalledTimes(1)
  await expect(resource.get(undefined, { fresh: true })).resolves.toBe('ok')
  stop()
  resource.dispose()
})

it('keeps a failed ordinary get stable and shares an explicitly fresh retry', async () => {
  const retried = deferred<string>()
  const read = vi
    .fn()
    .mockRejectedValueOnce(new ApiError(503, 'unavailable', '服务暂时不可用'))
    .mockReturnValue(retried.promise)
  const resource = new QueryResource<string>(read)
  await expect(resource.get()).rejects.toThrow('服务暂时不可用')
  await expect(resource.get()).rejects.toThrow('服务暂时不可用')
  expect(read).toHaveBeenCalledTimes(1)
  const first = resource.get(undefined, { fresh: true })
  const second = resource.get(undefined, { fresh: true })
  const passive = resource.get()
  retried.resolve('recovered')
  expect(await Promise.all([first, second, passive])).toEqual([
    'recovered',
    'recovered',
    'recovered',
  ])
  expect(read).toHaveBeenCalledTimes(2)
  resource.dispose()
})

it('revalidates an inactive resource on return and evicts abandoned requests within bounded lifetime', async () => {
  vi.useFakeTimers()
  const evict = vi.fn()
  const read = vi.fn().mockResolvedValue('first')
  const resource = new QueryResource<string>(read, evict)
  const stop = resource.subscribe(vi.fn())
  await resource.ensure()
  stop()
  await vi.advanceTimersByTimeAsync(1)
  const back = resource.subscribe(vi.fn())
  read.mockResolvedValue('updated')
  await resource.ensure()
  expect(resource.getSnapshot().data).toBe('updated')
  expect(read).toHaveBeenCalledTimes(2)
  back()
  await vi.advanceTimersByTimeAsync(30000)
  expect(evict).toHaveBeenCalledTimes(1)
})
