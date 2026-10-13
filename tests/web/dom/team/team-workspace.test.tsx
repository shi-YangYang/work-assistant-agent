// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { TeamReportRow, TeamWorkRow, TeamWorkspacePage } from '@paa/api-contracts'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../../../../apps/web/src/api/client'
import { TeamWorkspace } from '../../../../apps/web/src/features/team/components/TeamWorkspace'
import { createVault, deferred, TestWorkspace } from '../helpers'

vi.mock('@web/api/client', async (load) => ({
  ...(await load<typeof import('../../../../apps/web/src/api/client')>()),
  api: vi.fn(),
}))

const member = {
  id: 'employee',
  name: '张一',
  username: 'alpha',
  role: 'employee' as const,
  active: true,
  hasPassword: true,
}
const work: TeamWorkRow = {
  id: 'work',
  member,
  work: {
    id: 'work',
    ownerId: member.id,
    title: '整理客户反馈',
    summary: '工作内容',
    status: 'in_progress',
    blocker: '',
    nextStep: '',
    revision: 1,
    updatedAt: '2026-10-13T08:00:00Z',
  },
}
const report: TeamReportRow = {
  id: 'report',
  member,
  kind: 'daily',
  period: '2026-10-13',
  periodEnd: '2026-10-13',
  state: 'submitted',
  scheduled: true,
  deadlineAt: null,
  timezone: 'Asia/Shanghai',
  reportId: 'report',
  revision: 1,
  submittedAt: '2026-10-13T09:00:00Z',
  summary: '今日已完成客户回访',
}
function page<T>(item: T): TeamWorkspacePage<T> {
  return {
    items: [item],
    total: 1,
    nextCursor: null,
    counts: { all: 1, in_progress: 1, submitted: 1 },
    members: [member],
    range: {
      period: 'this_week',
      start: '2026-10-12',
      end: '2026-10-18',
      timezone: 'Asia/Shanghai',
    },
  }
}
function mount() {
  render(
    <MemoryRouter initialEntries={['/team']}>
      <TestWorkspace vault={createVault()}>
        <TeamWorkspace renderDetail={() => null} />
      </TestWorkspace>
    </MemoryRouter>,
  )
}
const switchTab = (name: string) =>
  fireEvent.click(within(screen.getByLabelText('看板视图')).getByRole('button', { name }))

beforeEach(() => vi.resetAllMocks())
afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

it('skips the loading notice when the first tab request finishes quickly without delaying its results', async () => {
  vi.useFakeTimers()
  const reports = deferred<unknown>()
  vi.mocked(api).mockImplementation(async (path) =>
    path.startsWith('/team/workspace/reports?') ? reports.promise : page(work),
  )
  await act(async () => mount())
  expect(screen.getByRole('heading', { name: work.work.title })).toBeTruthy()

  switchTab('日报周报')
  expect(screen.queryByText('正在读取团队记录…')).toBeNull()
  await act(async () => vi.advanceTimersByTime(100))
  expect(screen.queryByText('正在读取团队记录…')).toBeNull()
  await act(async () => reports.resolve(page(report)))
  expect(screen.getByText(report.summary)).toBeTruthy()
  await act(async () => vi.advanceTimersByTime(300))
  expect(screen.queryByText('正在读取团队记录…')).toBeNull()
})

it('shows a loading notice for a slow first request and removes it immediately on failure', async () => {
  vi.useFakeTimers()
  const reports = deferred<unknown>()
  vi.mocked(api).mockImplementation(async (path) =>
    path.startsWith('/team/workspace/reports?') ? reports.promise : page(work),
  )
  await act(async () => mount())
  switchTab('日报周报')
  await act(async () => vi.advanceTimersByTime(199))
  expect(screen.queryByText('正在读取团队记录…')).toBeNull()
  await act(async () => vi.advanceTimersByTime(1))
  expect(screen.getByRole('status').textContent).toBe('正在读取团队记录…')
  await act(async () => reports.reject(new Error('读取失败')))
  expect(screen.getByRole('alert').textContent).toContain('读取失败')
  expect(screen.queryByText('正在读取团队记录…')).toBeNull()
})

it('returns to either loaded tab without blanking rows, counts or employee options while refreshing', async () => {
  const workRefresh = deferred<unknown>(),
    reportRefresh = deferred<unknown>()
  let workReads = 0,
    reportReads = 0
  vi.mocked(api).mockImplementation(async (path) =>
    path.startsWith('/team/workspace/work?')
      ? ++workReads === 1
        ? page(work)
        : workRefresh.promise
      : ++reportReads === 1
        ? page(report)
        : reportRefresh.promise,
  )
  mount()
  await screen.findByRole('heading', { name: work.work.title })
  expect(reportReads).toBe(0)
  switchTab('日报周报')
  await screen.findByText(report.summary)

  switchTab('工作进展')
  expect(screen.getByRole('heading', { name: work.work.title })).toBeTruthy()
  expect(screen.queryByText('正在读取团队记录…')).toBeNull()
  expect(screen.queryByText(report.summary)).toBeNull()
  expect(
    within(screen.getByLabelText('工作状态筛选')).getByRole('button', { name: '全部工作 1' }),
  ).toBeTruthy()
  expect(
    within(screen.getByLabelText('选择员工')).getByRole('option', { name: member.name }),
  ).toBeTruthy()
  await waitFor(() => expect(workReads).toBe(2))
  await act(async () =>
    workRefresh.resolve(page({ ...work, work: { ...work.work, title: '已整理客户反馈' } })),
  )
  expect(screen.getByRole('heading', { name: '已整理客户反馈' })).toBeTruthy()

  switchTab('日报周报')
  expect(screen.getByText(report.summary)).toBeTruthy()
  expect(screen.queryByText('正在读取团队记录…')).toBeNull()
  expect(screen.getByText(/2026-10-12 — 2026-10-18/)).toBeTruthy()
  await waitFor(() => expect(reportReads).toBe(2))
})

it('does not apply a late response from an inactive tab or reuse rows under a different filter', async () => {
  const reports = deferred<unknown>(),
    filtered = deferred<unknown>()
  vi.mocked(api).mockImplementation(async (path) => {
    if (path.startsWith('/team/workspace/reports?')) return reports.promise
    if (path.includes('status=blocked')) return filtered.promise
    return page(work)
  })
  mount()
  await screen.findByRole('heading', { name: work.work.title })
  switchTab('日报周报')
  await waitFor(() => expect(api).toHaveBeenCalledTimes(2))
  const signal = vi.mocked(api).mock.calls[1][1]?.signal
  switchTab('工作进展')
  expect(screen.getByRole('heading', { name: work.work.title })).toBeTruthy()
  expect(signal?.aborted).toBe(true)
  await act(async () => reports.resolve(page(report)))
  expect(screen.queryByText(report.summary)).toBeNull()

  fireEvent.click(
    within(screen.getByLabelText('工作状态筛选')).getByRole('button', { name: /有阻碍/ }),
  )
  expect(screen.queryByRole('heading', { name: work.work.title })).toBeNull()
  await act(async () =>
    filtered.resolve({ ...page(work), items: [], total: 0, counts: { all: 0 } }),
  )
  expect(screen.getByText('暂无符合条件的工作')).toBeTruthy()
})
