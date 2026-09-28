// @vitest-environment jsdom
import type { CompanyService, Job, ModelCheck } from '@paa/api-contracts'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { StrictMode } from 'react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../../apps/web/src/api/client'
import { JobNotice } from '../../../apps/web/src/features/jobs/components/JobNotice'
import { retryJob } from '../../../apps/web/src/features/jobs/api/requests'
import { ModelServices } from '../../../apps/web/src/features/model-services/components/ModelServices'
import {
  checkServiceConfiguration,
  deleteModelService,
} from '../../../apps/web/src/features/model-services/api/requests'
import { newModel } from '../../../apps/web/src/features/model-services/utils/service-drafts'
import { createVault, deferred, dialogs, identity, TestWorkspace } from './helpers'

vi.mock('@web/api/client', async (load) => ({
  ...(await load<typeof import('../../../apps/web/src/api/client')>()),
  api: vi.fn(),
}))
vi.mock('@web/features/jobs/api/requests', () => ({ retryJob: vi.fn() }))
vi.mock('@web/features/model-services/api/requests', async (load) => ({
  ...(await load<typeof import('../../../apps/web/src/features/model-services/api/requests')>()),
  checkServiceConfiguration: vi.fn(),
  deleteModelService: vi.fn(),
}))
const failed = {
  id: 'job',
  kind: 'report',
  state: 'failed',
  error: '原模型不可用',
  attempt: 1,
} as Job
const service: CompanyService = {
  id: 'service-one',
  name: '第一个服务',
  baseUrl: 'https://example.com/v1',
  revision: 1,
  hasKey: true,
  updatedAt: '2026-09-25T00:00:00Z',
  models: [{ ...newModel('gpt-test'), protocolMode: 'manual' }],
}
const other = { ...service, id: 'service-two', name: '第二个服务' }
const admin = { ...identity, member: { ...identity.member, role: 'admin' as const } }
beforeEach(() => {
  dialogs()
  vi.clearAllMocks()
  localStorage.clear()
})
afterEach(cleanup)
it('offers one report retry, immediately shows queue feedback, and uses the current model', async () => {
  const pending = deferred<Job>(),
    refresh = vi.fn()
  vi.mocked(retryJob).mockReturnValueOnce(pending.promise)
  render(<JobNotice job={failed} refresh={refresh} />)
  expect(screen.getAllByRole('button')).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(screen.getByRole('status').textContent).toContain('排队')
  expect(screen.queryByText('原模型不可用')).toBeNull()
  expect(retryJob).toHaveBeenCalledExactlyOnceWith(failed, { useCurrentConfig: true })
  await act(async () => pending.resolve({ ...failed, state: 'queued', attempt: 2 }))
  expect(refresh).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('status').textContent).toContain('排队')
})
it('restores a single actionable error after retry rejection while keeping independent document choices', async () => {
  vi.mocked(retryJob).mockRejectedValueOnce(new Error('请先配置报告模型'))
  const mounted = render(<JobNotice job={failed} refresh={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  expect(await screen.findByText('请先配置报告模型')).toBeTruthy()
  expect(screen.getAllByRole('button')).toHaveLength(1)
  mounted.rerender(<JobNotice job={{ ...failed, kind: 'document' }} refresh={vi.fn()} />)
  expect(screen.getByText('使用当前配置重新处理')).toBeTruthy()
})
function models(services: CompanyService[], account = admin) {
  vi.mocked(api).mockImplementation(async () => ({
    services,
    routing: { assistant: null, report: null, asr: null, revision: 1 },
    environment: [],
  }))
  const vault = createVault(account)
  const router = createMemoryRouter([
    {
      path: '*',
      element: (
        <TestWorkspace vault={vault} account={account}>
          <ModelServices />
        </TestWorkspace>
      ),
    },
  ])
  return {
    ...render(
      <StrictMode>
        <RouterProvider router={router} />
      </StrictMode>,
    ),
    vault,
  }
}
it('automatically selects a sole service and invalidates test results when its connection changes', async () => {
  vi.mocked(checkServiceConfiguration).mockImplementation(async (_, body) => ({
    service: body.name,
    model: 'gpt-test',
    time: new Date().toISOString(),
    elapsedMs: 10,
    checks: [{ name: '文字', state: 'passed' }],
    usage: null,
    fingerprint: 'test',
    revision: 1,
    purpose: 'assistant',
    requestId: 'request',
    draftVersion: body.draftVersion,
  }))
  models([service])
  expect(await screen.findByLabelText('服务名称')).toBeTruthy()
  expect((screen.getByLabelText('服务名称') as HTMLInputElement).value).toBe(service.name)
  fireEvent.click(screen.getByRole('button', { name: '测试 gpt-test' }))
  fireEvent.click(screen.getByRole('button', { name: '开始测试' }))
  await screen.findByText('模型测试结果')
  fireEvent.change(screen.getByLabelText('服务名称'), { target: { value: '新配置' } })
  expect(screen.queryByText('模型测试结果')).toBeNull()
  expect(checkServiceConfiguration).toHaveBeenCalledTimes(1)
})
it('restores the selected service on return but never inherits another account selection', async () => {
  let mounted = models([service, other])
  fireEvent.click(await screen.findByRole('button', { name: /第二个服务/ }))
  expect((screen.getByLabelText('服务名称') as HTMLInputElement).value).toBe(other.name)
  mounted.unmount()
  mounted = models([service, other])
  await waitFor(() =>
    expect((screen.getByLabelText('服务名称') as HTMLInputElement).value).toBe(other.name),
  )
  mounted.unmount()
  const nextAdmin = { ...admin, member: { ...admin.member, id: 'new-admin' } }
  mounted = models([service, other], nextAdmin)
  await screen.findByRole('button', { name: /第二个服务/ })
  expect(screen.queryByLabelText('服务名称')).toBeNull()
  expect(within(screen.getByLabelText('模型服务列表')).getAllByRole('button')).toHaveLength(2)
})

it('selects and remembers the remaining service after the selected service is deleted', async () => {
  models([service, other])
  fireEvent.click(await screen.findByRole('button', { name: /第二个服务/ }))
  vi.mocked(deleteModelService).mockResolvedValueOnce({ ok: true })
  vi.mocked(api).mockResolvedValue({
    services: [service],
    routing: { assistant: null, report: null, asr: null, revision: 1 },
    environment: [],
  })
  fireEvent.click(screen.getByRole('button', { name: '删除当前模型服务' }))
  fireEvent.click(screen.getByRole('button', { name: '确认删除服务' }))
  await waitFor(() =>
    expect((screen.getByLabelText('服务名称') as HTMLInputElement).value).toBe(service.name),
  )
  expect(deleteModelService).toHaveBeenCalledExactlyOnceWith(other, { expectedRevision: 1 })
  expect(localStorage.getItem('paa:model-service:company:owner:admin')).toBe(service.id)
})

it('ignores a model test result from a different configuration version', async () => {
  const pending = deferred<ModelCheck>()
  vi.mocked(checkServiceConfiguration).mockReturnValueOnce(pending.promise)
  models([service])
  await screen.findByLabelText('服务名称')
  fireEvent.click(screen.getByRole('button', { name: '测试 gpt-test' }))
  fireEvent.click(screen.getByRole('button', { name: '开始测试' }))
  await act(async () =>
    pending.resolve({
      service: service.name,
      model: 'gpt-test',
      time: new Date().toISOString(),
      elapsedMs: 10,
      checks: [{ name: '文字', state: 'passed' }],
      usage: null,
      fingerprint: 'test',
      revision: 1,
      purpose: 'assistant',
      requestId: 'request',
      draftVersion: 'previous-configuration',
    }),
  )
  expect(screen.queryByText('模型测试结果')).toBeNull()
  expect(
    (screen.getByRole('button', { name: '测试 gpt-test' }) as HTMLButtonElement).disabled,
  ).toBe(false)
})
