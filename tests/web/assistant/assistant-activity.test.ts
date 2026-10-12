// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { AssistantActivityJob, Job } from '@paa/api-contracts'
import { epoch, expireSession, setCsrf } from '../../../apps/web/src/api/client'
import { reconnectJobFeedback, subscribeJobFeedback } from '../../../apps/web/src/api/job-feedback'
import {
  AssistantActivityStore,
  mountAssistantActivity,
  beginAssistantActivity,
  announceAssistantActivity,
} from '../../../apps/web/src/api/assistant-activity'

const sources: Source[] = []
class Source extends EventTarget {
  close = vi.fn()
  onerror: (() => void) | null = null
  onopen: (() => void) | null = null
  constructor(readonly url: string) {
    super()
    sources.push(this)
  }
  snapshot(job: AssistantActivityJob) {
    this.dispatchEvent(
      new MessageEvent('snapshot', {
        data: JSON.stringify({ ...job, jobId: job.id, text: '', error: '' }),
      }),
    )
  }
}
const job = (id = 'one', patch: Partial<AssistantActivityJob> = {}): AssistantActivityJob => ({
  id,
  targetId: `message-${id}`,
  conversationId: `chat-${id}`,
  state: 'running',
  stage: 'generating',
  attempt: 1,
  fence: 1,
  seq: 1,
  updatedAt: '2026-10-12T00:00:00Z',
  ...patch,
})
const response = (jobs: AssistantActivityJob[]) => new Response(JSON.stringify({ jobs }))
const receipt = (id = 'one') => ({
  jobId: id,
  messageId: `message-${id}`,
  conversationId: `chat-${id}`,
})
const disposers: (() => void)[] = []
const flush = () => vi.advanceTimersByTimeAsync(0)
function start() {
  const store = new AssistantActivityStore('company:person:employee')
  expect(store.generation).toBe(epoch)
  disposers.push(mountAssistantActivity(store))
  return store
}
beforeEach(() => {
  vi.useFakeTimers()
  sources.length = 0
  setCsrf('test')
  Object.defineProperty(document, 'hidden', { configurable: true, value: false })
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true })
  vi.stubGlobal('EventSource', Source)
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => response([])),
  )
})
afterEach(async () => {
  disposers.splice(0).forEach((dispose) => dispose())
  await flush()
  setCsrf('')
  vi.useRealTimers()
  vi.unstubAllGlobals()
})
it('hands an upload to the accepted job atomically and clears only that submission on failure', async () => {
  const store = start()
  await flush()
  const states: string[] = []
  store.subscribe(() => states.push(store.getSnapshot()))
  const sending = store.begin(),
    other = store.begin()
  sending.accepted(receipt())
  sending.finish()
  other.finish()
  expect(states).toEqual(['working'])
  sources[0].snapshot(job('one', { state: 'succeeded' }))
  expect(states).toEqual(['working', 'idle'])
  const failed = store.begin()
  failed.finish()
  expect(store.getSnapshot()).toBe('idle')
})
it('observes all conversations while keeping one connection per job shared with message consumers', async () => {
  vi.mocked(fetch).mockResolvedValueOnce(response([job(), job('two', { state: 'queued' })]))
  const store = start()
  await flush()
  expect(store.getSnapshot()).toBe('working')
  const release = subscribeJobFeedback('one', 'running', 1, 1, vi.fn(), vi.fn(), vi.fn())!
  expect(sources).toHaveLength(2)
  sources[0].snapshot(job('one', { seq: 2, state: 'awaiting_input' }))
  expect(store.getSnapshot()).toBe('working')
  sources[1].snapshot(job('two', { seq: 2, state: 'cancelled' }))
  expect(store.getSnapshot()).toBe('idle')
  release()
})
it('ignores a snapshot begun before a new receipt and a late snapshot after terminal feedback', async () => {
  let finish!: (value: Response) => void
  vi.mocked(fetch).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve
      }),
  )
  const store = start()
  await flush()
  store.begin().accepted(receipt())
  finish(response([]))
  await flush()
  expect(store.getSnapshot()).toBe('working')
  vi.mocked(fetch).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve
      }),
  )
  store.synchronize()
  await flush()
  sources[0].snapshot(job('one', { state: 'failed', seq: 5 }))
  finish(response([job()]))
  await flush()
  expect(store.getSnapshot()).toBe('idle')
})
it('a cancellation receipt supersedes feedback even when the Job DTO has no sequence', async () => {
  vi.mocked(fetch).mockResolvedValueOnce(response([job('one', { seq: 15 })]))
  const store = start()
  await flush()
  store.accept(receipt(), {
    ...job('one', { state: 'cancelled', updatedAt: '2026-10-12T00:01:00Z' }),
    kind: 'message',
    error: '',
    phase: 'assistant',
  } as Job)
  expect(store.getSnapshot()).toBe('idle')
})
it('settles only the observed execution and preserves other active conversations', async () => {
  vi.mocked(fetch).mockResolvedValueOnce(
    response([job('one', { attempt: 2, fence: 3, seq: 15 }), job('two')]),
  )
  const store = start()
  await flush()
  const completed = (id: string, attempt: number, fence: number): Job => ({
    id,
    targetId: `message-${id}`,
    kind: 'message',
    state: 'succeeded',
    phase: 'assistant',
    stage: 'complete',
    attempt,
    fence,
    error: '',
    updatedAt: '2026-10-12T00:01:00Z',
  })
  store.settle(completed('one', 1, 1))
  expect(sources[0].close).not.toHaveBeenCalled()
  store.settle(completed('two', 1, 1))
  expect(store.getSnapshot()).toBe('working')
  store.settle(completed('one', 2, 3))
  expect(store.getSnapshot()).toBe('idle')
  // A late snapshot cannot revive the persisted terminal execution.
  vi.mocked(fetch).mockResolvedValueOnce(response([job('one', { attempt: 2, fence: 3, seq: 15 })]))
  store.synchronize()
  await flush()
  expect(store.getSnapshot()).toBe('idle')
  expect(sources).toHaveLength(2)
})
it('accepts a new retry attempt but rejects old events and a stale active snapshot', async () => {
  vi.mocked(fetch).mockResolvedValueOnce(response([job()]))
  const store = start()
  await flush()
  const old = sources[0]
  old.snapshot(job('one', { state: 'failed', seq: 5 }))
  store.accept(receipt(), {
    ...job('one', { attempt: 2, fence: 3 }),
    kind: 'message',
    phase: 'assistant',
    error: '',
  } as Job)
  expect(sources).toHaveLength(2)
  old.snapshot(job('one', { state: 'cancelled', seq: 100 }))
  vi.mocked(fetch).mockResolvedValueOnce(response([job('one', { state: 'queued' })]))
  store.synchronize()
  await flush()
  expect(store.getSnapshot()).toBe('working')
  sources[1].snapshot(job('one', { attempt: 2, fence: 3, seq: 6, state: 'awaiting_retry' }))
  expect(store.getSnapshot()).toBe('idle')
})
it('shows unknown on disconnect, does not poll, and recovers once when online', async () => {
  vi.mocked(fetch).mockResolvedValueOnce(response([job()]))
  const store = start()
  await flush()
  sources[0].onerror?.()
  expect(store.getSnapshot()).toBe('unknown')
  await vi.advanceTimersByTimeAsync(120000)
  expect(fetch).toHaveBeenCalledTimes(1)
  vi.mocked(fetch).mockImplementation(async (url) =>
    String(url).endsWith('/feedback')
      ? new Response(JSON.stringify({ ...job(), jobId: 'one', text: '', error: '' }))
      : response([job()]),
  )
  window.dispatchEvent(new Event('online'))
  document.dispatchEvent(new Event('visibilitychange'))
  await flush()
  expect(store.getSnapshot()).toBe('working')
  expect(
    vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/assistant/activity')),
  ).toHaveLength(2)
  expect(sources).toHaveLength(2)
  expect(
    vi
      .mocked(fetch)
      .mock.calls.every(([, options]) => !options?.method || options.method === 'GET'),
  ).toBe(true)
})
it('does not mark all tasks idle on a failed snapshot and ignores window focus', async () => {
  vi.mocked(fetch).mockResolvedValueOnce(response([job()]))
  const store = start()
  await flush()
  vi.mocked(fetch).mockRejectedValueOnce(new TypeError('offline'))
  window.dispatchEvent(new Event('focus'))
  await flush()
  expect(fetch).toHaveBeenCalledTimes(1)
  document.dispatchEvent(new Event('visibilitychange'))
  await flush()
  expect(store.getSnapshot()).toBe('unknown')
})
it('coalesces account-specific cross-tab notifications but ignores other accounts', async () => {
  const store = start()
  await flush()
  window.dispatchEvent(new StorageEvent('storage', { key: 'paa-assistant-task:other:chat' }))
  await flush()
  expect(fetch).toHaveBeenCalledTimes(1)
  vi.mocked(fetch).mockResolvedValueOnce(response([job()]))
  for (let i = 0; i < 4; i++)
    window.dispatchEvent(
      new StorageEvent('storage', { key: 'paa-assistant-task:company:person:employee:chat' }),
    )
  await flush()
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(store.getSnapshot()).toBe('working')
})
it('does not rerender for token, stage or sequence changes and releases inaccessible tasks', async () => {
  vi.mocked(fetch).mockResolvedValueOnce(response([job()]))
  const store = start()
  await flush()
  const listener = vi.fn()
  store.subscribe(listener)
  sources[0].snapshot(job('one', { seq: 2, stage: 'searching' }))
  sources[0].snapshot(job('one', { seq: 3, stage: 'generating' }))
  expect(listener).not.toHaveBeenCalled()
  sources[0].dispatchEvent(new MessageEvent('unavailable', { data: '{"status":403}' }))
  expect(store.getSnapshot()).toBe('idle')
  expect(listener).toHaveBeenCalledTimes(1)
})
it.each([403, 404])(
  'recovers rediscovered activity after %s while the message consumer retains the stopped connection',
  async (status) => {
    vi.mocked(fetch).mockResolvedValueOnce(response([job()]))
    const store = start()
    await flush()
    const receive = vi.fn(),
      error = vi.fn()
    disposers.push(subscribeJobFeedback('one', 'running', 1, 1, receive, error, vi.fn())!)
    const old = sources[0]
    old.dispatchEvent(new MessageEvent('unavailable', { data: JSON.stringify({ status }) }))
    await flush()
    expect(store.getSnapshot()).toBe('idle')
    await reconnectJobFeedback('one')
    await reconnectJobFeedback('one', job('one', { attempt: 0 }))
    await reconnectJobFeedback('one', job('one', { state: 'succeeded' }))
    await vi.advanceTimersByTimeAsync(120000)
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(sources).toHaveLength(1)

    vi.mocked(fetch).mockImplementation(async (url) =>
      String(url).endsWith('/feedback')
        ? new Response(JSON.stringify({ ...job(), jobId: 'one', text: '', error: '' }))
        : response([job()]),
    )
    store.synchronize()
    await flush()
    expect(store.getSnapshot()).toBe('working')
    expect(sources).toHaveLength(2)
    expect(old.close).toHaveBeenCalledTimes(1)
    expect(receive).toHaveBeenLastCalledWith(expect.objectContaining({ state: 'running' }))
    expect(error).toHaveBeenLastCalledWith('')
    old.snapshot(job('one', { state: 'failed', seq: 99 }))
    expect(store.getSnapshot()).toBe('working')

    sources[1].dispatchEvent(new MessageEvent('unavailable', { data: JSON.stringify({ status }) }))
    await flush()
    vi.mocked(fetch).mockImplementation(async (url) =>
      String(url).endsWith('/feedback') ? new Response('{}', { status }) : response([job()]),
    )
    store.synchronize()
    await flush()
    expect(store.getSnapshot()).toBe('idle')
    expect(sources).toHaveLength(2)
    expect(fetch).toHaveBeenCalledTimes(5)
    await vi.advanceTimersByTimeAsync(120000)
    expect(fetch).toHaveBeenCalledTimes(5)
  },
)
it.each([403, 404])(
  'ignores a snapshot begun before unavailability (%s) but accepts later authoritative discovery',
  async (status) => {
    let finish!: (value: Response) => void
    vi.mocked(fetch)
      .mockResolvedValueOnce(response([job()]))
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve
          }),
      )
    const store = start()
    await flush()
    store.synchronize()
    await flush()
    sources[0].dispatchEvent(new MessageEvent('unavailable', { data: JSON.stringify({ status }) }))
    expect(store.getSnapshot()).toBe('idle')
    finish(response([job()]))
    await flush()
    expect(store.getSnapshot()).toBe('idle')
    expect(sources).toHaveLength(1)

    vi.mocked(fetch).mockResolvedValueOnce(response([job()]))
    store.synchronize()
    await flush()
    expect(store.getSnapshot()).toBe('working')
    expect(sources).toHaveLength(2)
    sources[1].snapshot(job('one', { state: 'succeeded', seq: 2 }))
    expect(store.getSnapshot()).toBe('idle')
  },
)
it('accepts a retry after unavailability without letting the old in-flight snapshot replace it', async () => {
  let finish!: (value: Response) => void
  vi.mocked(fetch)
    .mockResolvedValueOnce(response([job()]))
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve
        }),
    )
  const store = start()
  await flush()
  store.synchronize()
  await flush()
  sources[0].dispatchEvent(new MessageEvent('unavailable', { data: '{"status":403}' }))
  await flush()
  store.accept(receipt(), {
    ...job('one', { attempt: 2, fence: 3 }),
    kind: 'message',
    phase: 'assistant',
    error: '',
  } as Job)
  expect(store.getSnapshot()).toBe('working')
  finish(response([job()]))
  await flush()
  expect(sources).toHaveLength(2)
  sources[1].snapshot(job('one', { attempt: 2, fence: 3, seq: 2, state: 'succeeded' }))
  expect(store.getSnapshot()).toBe('idle')
})
it('clears subscriptions on logout and blocks old account uploads and delayed snapshots', async () => {
  let finish!: (value: Response) => void
  vi.mocked(fetch).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve
      }),
  )
  const store = start()
  await flush()
  const upload = beginAssistantActivity('company:person:employee')!
  store.accept(receipt())
  expireSession()
  expect(store.getSnapshot()).toBe('idle')
  await flush()
  expect(sources[0].close).toHaveBeenCalledTimes(1)
  setCsrf('next', 'different')
  const next = start()
  upload.accepted(receipt('old-upload'))
  upload.finish()
  finish(response([job()]))
  await flush()
  expect(next.getSnapshot()).toBe('idle')
  expect(sources).toHaveLength(1)
})
it('keeps initial discovery quiet and supports effect cleanup/remount without leaking sockets', async () => {
  const store = new AssistantActivityStore('same')
  const cleanup = mountAssistantActivity(store)
  cleanup()
  vi.mocked(fetch).mockResolvedValueOnce(response([job()]))
  disposers.push(mountAssistantActivity(store))
  expect(store.getSnapshot()).toBe('idle')
  await flush()
  expect(store.getSnapshot()).toBe('working')
  expect(sources).toHaveLength(1)
})

it('publishes one cross-tab change for the send and task hooks sharing the same receipt', async () => {
  const write = vi.spyOn(Storage.prototype, 'setItem')
  announceAssistantActivity('owner', 'chat')
  announceAssistantActivity('owner', 'chat')
  announceAssistantActivity('owner', 'chat')
  await flush()
  expect(write).toHaveBeenCalledTimes(1)
  expect(write).toHaveBeenCalledWith('paa-assistant-task:owner:chat', expect.any(String))
  write.mockRestore()
})

it('starts one fresh snapshot if online arrives before an aborted request settles', async () => {
  vi.mocked(fetch).mockImplementationOnce(
    (_url, options) =>
      new Promise((_resolve, reject) => {
        options?.signal?.addEventListener('abort', () =>
          reject(new DOMException('aborted', 'AbortError')),
        )
      }),
  )
  const store = start()
  await flush()
  vi.mocked(fetch).mockResolvedValueOnce(response([job()]))
  window.dispatchEvent(new Event('offline'))
  window.dispatchEvent(new Event('online'))
  await flush()
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(store.getSnapshot()).toBe('working')
})
