import { afterEach, expect, it, vi } from 'vitest'
import { setCsrf } from '../../apps/web/src/api/client'
import {
  feedbackDisconnected,
  reconnectJobFeedback,
  subscribeJobFeedback,
} from '../../apps/web/src/api/job-feedback'
class Source extends EventTarget {
  static current: Source
  onerror: (() => void) | null = null
  onopen: (() => void) | null = null
  close = vi.fn()
  constructor() {
    super()
    Source.current = this
  }
}
afterEach(() => {
  setCsrf('')
  vi.useRealTimers()
  vi.unstubAllGlobals()
})
it('stops all automatic requests after disconnect and recovers once on online without reposting', async () => {
  vi.useFakeTimers()
  const surface = Object.assign(new EventTarget(), {
    location: { pathname: '/assistant' },
    innerWidth: 1000,
    innerHeight: 800,
  })
  const document = Object.assign(new EventTarget(), { hidden: false })
  vi.stubGlobal('window', surface)
  vi.stubGlobal('document', document)
  vi.stubGlobal('navigator', { onLine: true, userAgent: '' })
  vi.stubGlobal('EventSource', Source)
  let finish!: (response: Response) => void
  const fetch = vi.fn<(url: string, options: RequestInit) => Promise<Response>>(
    () =>
      new Promise<Response>((resolve) => {
        finish = resolve
      }),
  )
  vi.stubGlobal('fetch', fetch)
  const receive = vi.fn(),
    error = vi.fn(),
    refresh = vi.fn(),
    expired = vi.fn()
  surface.addEventListener('paa-session-expired', expired)
  const dispose = subscribeJobFeedback('job', 'running', 1, 1, receive, error, refresh)!
  const source = Source.current
  source.onerror?.()
  expect(source.close).toHaveBeenCalledTimes(1)
  await vi.advanceTimersByTimeAsync(120000)
  expect(fetch).not.toHaveBeenCalled()
  expect(error).toHaveBeenLastCalledWith(feedbackDisconnected)
  surface.dispatchEvent(new Event('online'))
  void reconnectJobFeedback('job')
  document.dispatchEvent(new Event('visibilitychange'))
  expect(fetch).toHaveBeenCalledTimes(1)
  finish(
    new Response(JSON.stringify({ jobId: 'job', attempt: 1, fence: 1, seq: 1, state: 'running' })),
  )
  await vi.advanceTimersByTimeAsync(0)
  expect(receive).toHaveBeenCalledTimes(1)
  expect(Source.current).not.toBe(source)
  expect(fetch.mock.calls[0][0]).toBe('/api/v1/jobs/job/feedback')
  expect(fetch.mock.calls[0][1].method).not.toBe('POST')
  dispose()
  source.dispatchEvent(new MessageEvent('unavailable', { data: JSON.stringify({ status: 401 }) }))
  await vi.advanceTimersByTimeAsync(10000)
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(expired).not.toHaveBeenCalled()
})

it('respects Retry-After for explicit recovery without scheduling another request', async () => {
  vi.useFakeTimers()
  const surface = Object.assign(new EventTarget(), {
    location: { pathname: '/assistant' },
    innerWidth: 1000,
    innerHeight: 800,
  })
  const document = Object.assign(new EventTarget(), { hidden: false })
  vi.stubGlobal('window', surface)
  vi.stubGlobal('document', document)
  vi.stubGlobal('navigator', { onLine: true, userAgent: '' })
  vi.stubGlobal('EventSource', Source)
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(new Response('{}', { status: 429, headers: { 'Retry-After': '60' } }))
    .mockImplementation(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({ jobId: 'job', attempt: 1, fence: 1, seq: 1, state: 'running' }),
        ),
      ),
    )
  vi.stubGlobal('fetch', fetch)
  const receive = vi.fn()
  const dispose = subscribeJobFeedback('job', 'running', 1, 1, receive, vi.fn(), vi.fn())!
  try {
    const source = Source.current
    source.onerror?.()
    await reconnectJobFeedback('job')
    expect(fetch).toHaveBeenCalledTimes(1)
    for (let count = 0; count < 3; count++) {
      surface.dispatchEvent(new Event('online'))
      document.dispatchEvent(new Event('visibilitychange'))
      await vi.advanceTimersByTimeAsync(10000)
    }
    expect(fetch).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(29999)
    expect(fetch).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(fetch).toHaveBeenCalledTimes(1)
    await reconnectJobFeedback('job')
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(receive).toHaveBeenCalledTimes(1)
    expect(source.close).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(5000)
    expect(fetch).toHaveBeenCalledTimes(2)
  } finally {
    dispose()
  }
})

it('delivers committed cards while running and refreshes when access is revoked', async () => {
  const surface = Object.assign(new EventTarget(), {
    location: { pathname: '/assistant' },
    innerWidth: 1000,
    innerHeight: 800,
  })
  vi.stubGlobal('window', surface)
  vi.stubGlobal('document', Object.assign(new EventTarget(), { hidden: false }))
  vi.stubGlobal('navigator', { onLine: true, userAgent: '' })
  vi.stubGlobal('EventSource', Source)
  const receive = vi.fn(),
    refresh = vi.fn()
  const dispose = subscribeJobFeedback('job', 'running', 1, 1, receive, vi.fn(), refresh)!
  try {
    const live = {
      jobId: 'job',
      attempt: 1,
      fence: 1,
      seq: 2,
      state: 'running',
      actions: [{ id: 'saved', state: 'succeeded' }],
    }
    Source.current.dispatchEvent(new MessageEvent('snapshot', { data: JSON.stringify(live) }))
    expect(receive).toHaveBeenLastCalledWith(live)
    expect(refresh).not.toHaveBeenCalled()
    Source.current.dispatchEvent(new MessageEvent('unavailable', { data: '{"status":403}' }))
    expect(receive).toHaveBeenLastCalledWith(null)
    expect(refresh).toHaveBeenCalledTimes(1)
  } finally {
    dispose()
  }
})

it('accepts fresh card invalidation even when the worker phase has not advanced', async () => {
  const { acceptFeedback } = await import('../../apps/web/src/api/job-feedback')
  const current = {
    jobId: 'job',
    attempt: 1,
    fence: 1,
    seq: 2,
    state: 'running' as const,
    stage: 'generating',
    text: '',
    error: '',
    updatedAt: '2026-09-20T01:00:00Z',
    actions: [],
  }
  const changed = { ...current, actions: [{ id: 'saved', state: 'unavailable' }] }
  // The provider's next token is independent of target version/permission changes.
  expect(acceptFeedback(current, changed as typeof current, 'job')).toBe(changed)
  expect(acceptFeedback(current, { ...current, seq: 1 }, 'job')).toBe(current)
})

it.each(['succeeded', 'awaiting_input', 'failed', 'awaiting_retry', 'cancelled'])(
  'closes a %s task and never reconnects after online or manual retry',
  async (state) => {
    vi.useFakeTimers()
    const surface = new EventTarget()
    vi.stubGlobal('window', surface)
    vi.stubGlobal('navigator', { onLine: true, userAgent: '' })
    vi.stubGlobal('EventSource', Source)
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    const refresh = vi.fn(),
      error = vi.fn()
    const dispose = subscribeJobFeedback('terminal', 'running', 1, 1, vi.fn(), error, refresh)!
    try {
      const source = Source.current
      source.dispatchEvent(
        new MessageEvent('snapshot', {
          data: JSON.stringify({ jobId: 'terminal', attempt: 1, fence: 1, seq: 2, state }),
        }),
      )
      source.onerror?.()
      surface.dispatchEvent(new Event('online'))
      await reconnectJobFeedback('terminal')
      await vi.advanceTimersByTimeAsync(60000)
      expect(source.close).toHaveBeenCalledTimes(1)
      expect(error).toHaveBeenLastCalledWith('')
      expect(refresh).toHaveBeenCalledTimes(1)
      expect(fetch).not.toHaveBeenCalled()
      subscribeJobFeedback('persisted-terminal', state, 1, 1, vi.fn(), error, refresh)
      expect(Source.current).toBe(source)
    } finally {
      dispose()
    }
  },
)

it('loads the final status once after disconnect without opening another stream', async () => {
  vi.stubGlobal('window', new EventTarget())
  vi.stubGlobal('navigator', { onLine: true, userAgent: '' })
  vi.stubGlobal('EventSource', Source)
  const fetch = vi.fn(
    async () =>
      new Response(
        JSON.stringify({
          jobId: 'finished',
          attempt: 1,
          fence: 1,
          seq: 4,
          state: 'failed',
          error: '模型调用失败',
        }),
      ),
  )
  vi.stubGlobal('fetch', fetch)
  const receive = vi.fn(),
    refresh = vi.fn(),
    error = vi.fn()
  const dispose = subscribeJobFeedback('finished', 'running', 1, 1, receive, error, refresh)!
  try {
    const source = Source.current
    source.onerror?.()
    await reconnectJobFeedback('finished')
    await reconnectJobFeedback('finished')
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(Source.current).toBe(source)
    expect(receive).toHaveBeenLastCalledWith(expect.objectContaining({ state: 'failed' }))
    expect(refresh).toHaveBeenCalledTimes(1)
    expect(error).toHaveBeenLastCalledWith('')
  } finally {
    dispose()
  }
})

it('ignores an older terminal event without closing the healthy stream or refetching results', () => {
  vi.stubGlobal('window', new EventTarget())
  vi.stubGlobal('navigator', { onLine: true, userAgent: '' })
  vi.stubGlobal('EventSource', Source)
  const receive = vi.fn(),
    refresh = vi.fn()
  const dispose = subscribeJobFeedback('ordered', 'running', 1, 1, receive, vi.fn(), refresh)!
  const source = Source.current
  const emit = (seq: number, state: string) =>
    source.dispatchEvent(
      new MessageEvent('snapshot', {
        data: JSON.stringify({
          jobId: 'ordered',
          attempt: 1,
          fence: 1,
          seq,
          state,
          stage: 'generating',
          updatedAt: '2026-09-29',
        }),
      }),
    )
  emit(10, 'running')
  emit(5, 'failed')
  expect(source.close).not.toHaveBeenCalled()
  expect(refresh).not.toHaveBeenCalled()
  expect(receive).toHaveBeenCalledTimes(1)
  emit(11, 'succeeded')
  expect(source.close).toHaveBeenCalledTimes(1)
  expect(refresh).toHaveBeenCalledTimes(1)
  dispose()
})
