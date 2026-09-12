import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, setCsrf, write, todayIn } from '../../src/web/api'
afterEach(() => {
  vi.unstubAllGlobals()
  setCsrf('')
})
describe('company HTTP boundary', () => {
  it('sends CSRF and stable operation keys with same-origin credentials', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ saved: true }) })
    vi.stubGlobal('fetch', fetch)
    setCsrf('test-csrf')
    await write('/messages', { text: '进展' }, 'POST', 'fixed-request')
    const options = fetch.mock.calls[0][1]
    expect(options.headers.get('X-CSRF-Token')).toBe('test-csrf')
    expect(options.headers.get('Idempotency-Key')).toBe('fixed-request')
    expect(options.credentials).toBe('same-origin')
  })
  it('preserves server revision conflict rather than returning a fake success', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue({
          ok: false,
          status: 409,
          json: async () => ({ error: { code: 'revision_conflict', message: '请读取最新版本' } }),
        }),
    )
    await expect(api('/reports/report')).rejects.toMatchObject({
      status: 409,
      code: 'revision_conflict',
    } satisfies Partial<ApiError>)
  })
  it('formats a calendar day in company timezone', () => {
    expect(todayIn('Asia/Shanghai')).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })
})
