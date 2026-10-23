// @vitest-environment jsdom
import type { Report, Rules } from '@paa/api-contracts'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, write } from '../../../../apps/web/src/api/client'
import { ReportDetail } from '../../../../apps/web/src/features/reports/components/detail/ReportDetail'
import { ReportHeader } from '../../../../apps/web/src/features/reports/components/detail/ReportHeader'
import { RulesPage } from '../../../../apps/web/src/features/settings/components/rules/RulesPage'
import { createVault, deferred, dialogs, identity, TestWorkspace } from '../helpers'

vi.mock('@web/api/client', async (load) => ({
  ...(await load<typeof import('../../../../apps/web/src/api/client')>()),
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
  kind: 'weekly',
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
it.each([
  ['weekly', '2026-10-12', '2026-10-18', '周报', '2026/10/12 — 10/18'],
  ['weekly', '2026-12-28', '2027-01-03', '周报', '2026/12/28 — 2027/01/03'],
] as const)('keeps %s report metadata compact for %s', (kind, period, periodEnd, title, range) => {
  render(
    <ReportHeader
      compact={false}
      report={{ ...report, kind, period, periodEnd, ownerName: '段晓华' }}
    />,
  )
  expect(screen.getByRole('heading', { name: title })).toBeTruthy()
  expect(screen.getByText('草稿')).toBeTruthy()
  expect(screen.getByText(range)).toBeTruthy()
  expect(screen.getByText('段晓华').parentElement).toBe(screen.getByText('北京时间').parentElement)
  expect(screen.getByText('北京时间').title).toContain('UTC+08:00')
})
it('keeps return and management in navigation while retaining the report submission flow', async () => {
  vi.mocked(api).mockImplementation(async (path) =>
    path.includes('/sources') ? { items: [] } : report,
  )
  vi.mocked(write).mockResolvedValue({ ok: true })
  render(
    <MemoryRouter
      initialEntries={[
        {
          pathname: '/reports/report',
          state: { returnTo: { path: '/assistant/current', state: null } },
        },
      ]}
    >
      <TestWorkspace vault={createVault()}>
        <ReportDetail recordId="report" />
      </TestWorkspace>
    </MemoryRouter>,
  )
  const navigation = screen.getByRole('navigation', { name: '报告导航' })
  expect(within(navigation).getByRole('link', { name: '返回会话' }).getAttribute('href')).toBe(
    '/assistant/current',
  )
  fireEvent.click(await within(navigation).findByRole('button', { name: '管理报告' }))
  expect(screen.getByRole('menuitem', { name: '删除报告' })).toBeTruthy()
  fireEvent.click(within(navigation).getByRole('button', { name: '管理报告' }))
  const actions = screen.getByRole('group', { name: '报告操作' })
  expect(within(actions).getByRole('button', { name: '编辑草稿' })).toBeTruthy()
  fireEvent.click(within(actions).getByRole('button', { name: '提交报告' }))
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '确认提交' }))
  await waitFor(() =>
    expect(write).toHaveBeenCalledWith(
      '/reports/report/submit',
      { expectedRevision: 1 },
      'POST',
      expect.any(String),
    ),
  )
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
})
it('keeps embedded historical reports read-only without adding standalone navigation', async () => {
  vi.mocked(api).mockImplementation(async (path) =>
    path.includes('/sources')
      ? { items: [] }
      : { ...report, historical: true, revision: 2, publishedRevision: 3 },
  )
  render(
    <MemoryRouter initialEntries={['/team']}>
      <TestWorkspace vault={createVault()}>
        <ReportDetail compact recordId="report" />
      </TestWorkspace>
    </MemoryRouter>,
  )
  expect(await screen.findByText('已提交第 2 版')).toBeTruthy()
  expect(screen.queryByRole('navigation', { name: '报告导航' })).toBeNull()
  expect(screen.queryByRole('group', { name: '报告操作' })).toBeNull()
  expect(screen.queryByRole('button', { name: '管理报告' })).toBeNull()
})
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
