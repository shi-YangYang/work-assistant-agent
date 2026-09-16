import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, setCsrf, write, todayIn, requestBudget } from '../../apps/web/src/api'
const requestId = '11111111-2222-3333-4444-555555555555'
const response = (body: unknown, status = 200, headers?: HeadersInit) =>
  new Response(JSON.stringify(body), { status, headers })
let surface: EventTarget & {
  location: { pathname: string }
  innerWidth: number
  innerHeight: number
}
beforeEach(() => {
  surface = Object.assign(new EventTarget(), {
    location: { pathname: '/assistant/private-id' },
    innerWidth: 390,
    innerHeight: 844,
  })
  vi.stubGlobal('window', surface)
  setCsrf('')
})
afterEach(() => {
  setCsrf('')
  vi.useRealTimers()
  vi.unstubAllGlobals()
})
describe('company HTTP boundary', () => {
  it('sends CSRF and stable operation keys with same-origin credentials', async () => {
    const fetch = vi.fn().mockResolvedValue(response({ saved: true }))
    vi.stubGlobal('fetch', fetch)
    setCsrf('test-csrf')
    await write('/messages', { text: '进展' }, 'POST', 'fixed-request')
    const options = fetch.mock.calls[0][1]
    expect(options.headers.get('X-CSRF-Token')).toBe('test-csrf')
    expect(options.headers.get('Idempotency-Key')).toBe('fixed-request')
    expect(options.credentials).toBe('same-origin')
  })
  it('preserves safe validation/conflict messages and the originating request ID', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          response(
            { error: { code: 'revision_conflict', message: '请读取最新版本', requestId } },
            409,
          ),
        ),
    )
    await expect(api('/reports/report')).rejects.toMatchObject({
      status: 409,
      code: 'revision_conflict',
      message: '请读取最新版本',
      requestId,
      diagnostics: { page: '/assistant/:conversationId', requestId },
    } satisfies Partial<ApiError>)
  })
  it.each([
    ['<html>private upstream body</html>', 200, 'invalid_response'],
    ['', 200, 'invalid_response'],
    ['<h1>Proxy trace and secret</h1>', 502, 'server'],
  ])('sanitizes invalid response %s', async (body, status, category) => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          new Response(body, { status: Number(status), headers: { 'X-Request-ID': requestId } }),
        ),
    )
    const failure = await api('/work-items').catch((error: ApiError) => error)
    expect(failure).toMatchObject({ category, requestId })
    expect((failure as ApiError).message).not.toMatch(/html|secret|trace|Proxy/)
  })
  it('accepts explicit empty success only as 204', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
    await expect(api('/operation')).resolves.toBeUndefined()
  })
  it.each([403, 429, 503])(
    'classifies HTTP %s without copying upstream details',
    async (status) => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(
          response({ error: { message: '<html>secret</html>', requestId } }, status, {
            'Retry-After': '12',
          }),
        ),
      )
      const failure = (await api('/work-items').catch((error: ApiError) => error)) as ApiError
      expect(failure.message).not.toContain('secret')
      expect(failure.category).toBe(
        { 403: 'forbidden', 429: 'rate_limited', 503: 'server' }[status],
      )
      if (status === 429) expect(failure.message).toContain('12 秒')
    },
  )
  it('distinguishes network failure and never replays writes', async () => {
    const fetch = vi.fn().mockRejectedValue(new TypeError('fetch failed at private URL'))
    vi.stubGlobal('fetch', fetch)
    await expect(write('/messages', { text: 'sensitive' }, 'POST', 'one')).rejects.toMatchObject({
      category: 'network',
      status: 0,
      requestId: null,
    })
    expect(fetch).toHaveBeenCalledTimes(1)
  })
  it('bounds reads, uploads and model probes; active abort stays silent', async () => {
    vi.useFakeTimers()
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_path: string, options: RequestInit) =>
          new Promise((_resolve, reject) =>
            options.signal?.addEventListener('abort', () =>
              reject(new DOMException('Aborted', 'AbortError')),
            ),
          ),
      ),
    )
    const waiting = api('/work-items').catch((error: ApiError) => error)
    await vi.advanceTimersByTimeAsync(30000)
    expect(await waiting).toMatchObject({ category: 'timeout' })
    const controller = new AbortController()
    const cancelled = api('/work-items', { signal: controller.signal }).catch(
      (error: ApiError) => error,
    )
    controller.abort()
    expect(await cancelled).toMatchObject({ category: 'cancelled', message: '' })
    expect(requestBudget('/uploads')).toBeGreaterThan(requestBudget('/work-items'))
    expect(requestBudget('/settings/model-services/test')).toBeGreaterThan(
      requestBudget('/uploads'),
    )
  })
  it('expires once, aborts authorized requests and rejects late old-session reads after relogin', async () => {
    const expire = vi.fn()
    surface.addEventListener('paa-session-expired', expire)
    let finish!: (value: Response) => void
    const fetch = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            finish = resolve
          }),
      )
      .mockResolvedValueOnce(response({ error: { code: 'login_required' } }, 401))
    vi.stubGlobal('fetch', fetch)
    setCsrf('old')
    const old = api('/reports/old').catch((error: ApiError) => error)
    await expect(api('/work-items')).rejects.toMatchObject({ status: 401 })
    await expect(api('/messages')).rejects.toMatchObject({ category: 'cancelled' })
    expect(fetch).toHaveBeenCalledTimes(2)
    setCsrf('new')
    finish(response({ error: { code: 'login_required' } }, 401))
    expect(await old).toMatchObject({ category: 'cancelled' })
    expect(expire).toHaveBeenCalledTimes(1)
  })
  it('does not expire a session for a failed login or discard drafts for a CSRF rejection', async () => {
    const expire = vi.fn(),
      forbidden = vi.fn()
    surface.addEventListener('paa-session-expired', expire)
    surface.addEventListener('paa-access-forbidden', forbidden)
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(response({ error: { code: 'invalid_request' } }, 401))
        .mockResolvedValueOnce(
          response(
            { error: { code: 'csrf_rejected', message: '请求校验失败，请刷新后重试' } },
            403,
          ),
        ),
    )
    await expect(api('/auth/login')).rejects.toThrow('账号或密码')
    await expect(api('/messages')).rejects.toThrow('请求校验失败')
    expect(expire).not.toHaveBeenCalled()
    expect(forbidden).not.toHaveBeenCalled()
  })
  it('clears drafts before closing a session whose account permissions changed', async () => {
    const events: string[] = []
    surface.addEventListener('paa-access-forbidden', () => events.push('clear'))
    surface.addEventListener('paa-session-expired', () => events.push('expire'))
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          response({ error: { code: 'forbidden', message: '账号权限已变化，请重新登录' } }, 403),
        ),
    )
    setCsrf('old')
    await expect(api('/messages')).rejects.toMatchObject({ status: 403 })
    expect(events).toEqual(['clear', 'expire'])
    await expect(api('/work-items')).rejects.toMatchObject({ category: 'cancelled' })
  })
  it('formats a calendar day in company timezone', () => {
    expect(todayIn('Asia/Shanghai')).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })
})

it('loads private PDF bytes with the same identity epoch and error handling as JSON', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('%PDF-1.7', { status: 200 })))
  const bytes = await api<ArrayBuffer>('/uploads/file/content', {}, 'bytes')
  expect(new TextDecoder().decode(bytes)).toBe('%PDF-1.7')
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ error: { code: 'not_found' } }, 404)))
  await expect(api('/uploads/file/content', {}, 'bytes')).rejects.toMatchObject({ status: 404 })
  let resolve!: (value: ArrayBuffer) => void
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      arrayBuffer: () =>
        new Promise<ArrayBuffer>((done) => {
          resolve = done
        }),
    }),
  )
  const pending = api('/uploads/file/content', {}, 'bytes')
  await Promise.resolve()
  setCsrf('different-session')
  resolve(new TextEncoder().encode('late').buffer)
  await expect(pending).rejects.toMatchObject({ category: 'cancelled' })
})
