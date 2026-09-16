import { afterEach, expect, it, vi } from 'vitest'
import { captureDiagnostics, diagnosticPage, diagnosticText } from '../../apps/web/src/diagnostics'
afterEach(() => vi.unstubAllGlobals())
it('uses only route templates and coarse browser data; never includes URL query, body or raw user agent', () => {
  vi.stubGlobal('window', {
    location: { pathname: '/assistant/secret-conversation', search: '?token=private' },
    innerWidth: 390,
    innerHeight: 844,
  })
  vi.stubGlobal('navigator', {
    userAgent:
      'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Version/18.0 Mobile/15E148 Safari/604.1',
    cookie: 'secret-cookie',
  })
  const value = captureDiagnostics()
  expect(value).toMatchObject({
    page: '/assistant/:conversationId',
    browser: 'Safari 18.0',
    os: 'iOS 18.0',
    viewport: '390x844',
    requestId: null,
  })
  expect(diagnosticText(value)).not.toMatch(/secret|private|token|Cookie|Mozilla/)
  expect(diagnosticText(value)).toContain('请求编号：未知')
  expect(diagnosticPage('/unknown/customer-secret')).toBeNull()
  expect(diagnosticPage('/work/private-id')).toBe('/work/:id')
})
