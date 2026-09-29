// @vitest-environment jsdom
import type { Report, Rules } from '@paa/api-contracts'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, write } from '../../../apps/web/src/api/client'
import { ReportDetail } from '../../../apps/web/src/features/reports/components/detail/ReportDetail'
import { RulesPage } from '../../../apps/web/src/features/settings/components/rules/RulesPage'
import { createVault, deferred, dialogs, identity, TestWorkspace } from './helpers'

vi.mock('@web/api/client', async (load) => ({
  ...(await load<typeof import('../../../apps/web/src/api/client')>()),
  api: vi.fn(),
  write: vi.fn(),
}))
beforeEach(() => {
  dialogs()
  vi.clearAllMocks()
})
afterEach(cleanup)
const report: Report = {
  id: 'report',
  ownerId: 'owner',
  kind: 'daily',
  period: '2026-09-22',
  periodEnd: '2026-09-22',
  timezone: 'Asia/Shanghai',
  revision: 1,
  publishedRevision: 0,
  managementRevision: 1,
  content: { completed: '初稿', ongoing: '', blockers: '', next: '' },
  candidate: null,
  job: null,
  revisions: [],
  updatedAt: '2026-09-22T00:00:00Z',
  sourceIds: [],
}
it('locks report fields during save and preserves the reopened draft from a stale response', async () => {
  vi.mocked(api).mockImplementation(async (path) =>
    path.includes('/sources') ? { items: [] } : report,
  )
  const request = deferred<unknown>(),
    vault = createVault()
  vi.mocked(write).mockReturnValueOnce(request.promise)
  render(
    <MemoryRouter initialEntries={['/reports/report?edit=1']}>
      <TestWorkspace vault={vault}>
        <ReportDetail recordId="report" />
      </TestWorkspace>
    </MemoryRouter>,
  )
  const first = (await screen.findAllByRole('textbox'))[0] as HTMLTextAreaElement
  fireEvent.change(first, { target: { value: '待保存报告' } })
  fireEvent.click(screen.getByRole('button', { name: '保存草稿' }))
  expect(
    screen.getAllByRole('textbox').every((input) => (input as HTMLTextAreaElement).disabled),
  ).toBe(true)
  fireEvent.click(screen.getByText('稍后继续'))
  fireEvent.click(screen.getByText('编辑草稿'))
  fireEvent.change(screen.getAllByRole('textbox')[0], { target: { value: '后续报告' } })
  await act(async () => request.resolve({ ok: true }))
  expect((screen.getAllByRole('textbox')[0] as HTMLTextAreaElement).value).toBe('后续报告')
  expect(vault.getSnapshot()['report:report']).toMatchObject({ content: { completed: '后续报告' } })
})
it('locks all rule fields and time buttons until failure, retaining the edited rules', async () => {
  const schedule = {
    enabled: true,
    days: [0],
    generateTime: '17:00',
    deadline: '18:00',
    reminders: true,
    beforeMinutes: 30,
  }
  const rules = {
    revision: 1,
    timezone: 'Asia/Shanghai',
    daily: schedule,
    weekly: schedule,
  } as Rules
  vi.mocked(api).mockResolvedValue(rules)
  const request = deferred<unknown>(),
    account = { ...identity, member: { ...identity.member, role: 'admin' as const } },
    vault = createVault(account)
  vi.mocked(write).mockReturnValueOnce(request.promise)
  render(
    <TestWorkspace vault={vault} account={account}>
      <RulesPage />
    </TestWorkspace>,
  )
  const zone = (await screen.findByLabelText('公司时区')) as HTMLSelectElement
  fireEvent.change(zone, { target: { value: 'Asia/Tokyo' } })
  fireEvent.click(screen.getByText('保存汇报规则'))
  const form = zone.closest('form')!
  expect(
    [...form.querySelectorAll('input,select')].every(
      (field) => (field as HTMLInputElement).disabled,
    ),
  ).toBe(true)
  await act(async () => request.reject(new Error('保存失败')))
  await waitFor(() => expect(zone.disabled).toBe(false))
  expect(zone.value).toBe('Asia/Tokyo')
  expect(vault.getSnapshot().rules).toMatchObject({ timezone: 'Asia/Tokyo' })
})
