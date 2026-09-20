import { afterEach, expect, it, vi } from 'vitest'
import { setCsrf } from '../../apps/web/src/api/client'
import { subscribeJobFeedback } from '../../apps/web/src/api/job-feedback'
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
it('closes SSE before single-flight polling and ignores stale unauthorized events after disposal', async () => {
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
  const fetch = vi.fn(
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
  await vi.advanceTimersByTimeAsync(1000)
  expect(fetch).toHaveBeenCalledTimes(1)
  surface.dispatchEvent(new Event('online'))
  document.dispatchEvent(new Event('visibilitychange'))
  expect(fetch).toHaveBeenCalledTimes(1)
  finish(
    new Response(JSON.stringify({ jobId: 'job', attempt: 1, fence: 1, seq: 1, state: 'running' })),
  )
  await vi.advanceTimersByTimeAsync(0)
  expect(receive).toHaveBeenCalledTimes(1)
  dispose()
  source.dispatchEvent(new MessageEvent('unavailable', { data: JSON.stringify({ status: 401 }) }))
  await vi.advanceTimersByTimeAsync(10000)
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(expired).not.toHaveBeenCalled()
})

it('keeps online and visibility recovery behind Retry-After, then resumes one polling channel', async () => {
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
    await vi.advanceTimersByTimeAsync(1000)
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
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(receive).toHaveBeenCalledTimes(1)
    expect(source.close).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(5000)
    expect(fetch).toHaveBeenCalledTimes(3)
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
