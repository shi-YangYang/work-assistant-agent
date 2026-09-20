import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, setCsrf } from '../../apps/web/src/api/client'
import { sendMessage } from '../../apps/web/src/features/assistant/api/requests'
import { startDingTalkRedirect } from '../../apps/web/src/features/auth/api/requests'
import { saveModelService } from '../../apps/web/src/features/model-services/api/requests'
import { reportObligationsPath } from '../../apps/web/src/features/reports/api/requests'
import { workListPath } from '../../apps/web/src/features/work/api/requests'
const request = vi.fn()
beforeEach(() => {
  vi.stubGlobal(
    'window',
    Object.assign(new EventTarget(), {
      location: { pathname: '/work' },
      innerWidth: 1024,
      innerHeight: 768,
    }),
  )
  vi.stubGlobal(
    'fetch',
    request.mockImplementation(() => Promise.resolve(new Response('{}'))),
  )
  setCsrf('session-token')
})
afterEach(() => {
  setCsrf('')
  request.mockReset()
  vi.unstubAllGlobals()
})
it('preserves complete search/status filters and employee/team obligation scopes', async () => {
  await api(workListPath('中文 & notes', 'blocked'))
  expect(request.mock.calls[0][0]).toBe(
    '/api/v1/work-items?q=%E4%B8%AD%E6%96%87+%26+notes&status=blocked',
  )
  const query = new URLSearchParams({ kind: 'daily', date: '2026-09-20' })
  expect(reportObligationsPath(false, query)).toBe('/report-obligations?kind=daily&date=2026-09-20')
  expect(reportObligationsPath(true, query)).toBe(
    '/team/report-obligations?kind=daily&date=2026-09-20',
  )
})
it('creates a conversation only with the explicit message submission and retains its idempotency key', async () => {
  const body = { newConversation: true, text: '记录进展', attachmentIds: ['file'], replyTo: null }
  await sendMessage(body, 'stable-operation')
  const [path, options] = request.mock.calls[0]
  expect(path).toBe('/api/v1/messages')
  expect(options.method).toBe('POST')
  expect(JSON.parse(options.body)).toEqual(body)
  expect(options.headers.get('Idempotency-Key')).toBe('stable-operation')
  expect(options.headers.get('X-CSRF-Token')).toBe('session-token')
})
it('keeps model-service create/update revision payload and DingTalk intent endpoints', async () => {
  const service = {
    id: 'service',
    name: '公司模型',
    baseUrl: 'https://example.com/v1',
    models: [],
    revision: 0,
    hasKey: false,
  }
  const payload = {
    name: service.name,
    baseUrl: service.baseUrl,
    models: [],
    expectedRevision: 0,
    apiKey: 'test-key',
  }
  await saveModelService(service, payload, 'POST')
  await saveModelService({ ...service, revision: 4 }, { ...payload, expectedRevision: 4 }, 'PATCH')
  expect(
    request.mock.calls.map(([path, options]) => [
      path,
      options.method,
      JSON.parse(options.body).expectedRevision,
    ]),
  ).toEqual([
    ['/api/v1/settings/model-services', 'POST', 0],
    ['/api/v1/settings/model-services/service', 'PATCH', 4],
  ])
  await startDingTalkRedirect('reauthenticate', {})
  expect(request.mock.calls[2][0]).toBe('/api/v1/auth/dingtalk/account/reauth')
})
