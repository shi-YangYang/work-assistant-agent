// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, expect, it, vi } from 'vitest'
import { generateReport } from '../../../../apps/web/src/features/reports/api/requests'
import { ReportsPage } from '../../../../apps/web/src/features/reports/components/overview/ReportsOverview'

vi.mock('@web/hooks/usePagedResource', () => ({
  usePagedResource: () => ({ data: { items: [] }, refresh: vi.fn() }),
}))
vi.mock('@web/hooks/useResource', () => ({
  useResource: () => ({ data: { timezone: 'Asia/Shanghai' } }),
}))
vi.mock('@web/lib/workspace', () => ({ useWorkspace: () => ({ notify: vi.fn() }) }))
vi.mock('@web/features/reports/api/requests', async (load) => ({
  ...(await load<typeof import('../../../../apps/web/src/features/reports/api/requests')>()),
  generateReport: vi.fn(),
}))

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.clearAllMocks()
})

it('shows the actual reporting week before generation and keeps the current-week shortcut and rejects legacy daily navigation', async () => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-10-23T12:00:00Z'))
  vi.mocked(generateReport).mockRejectedValueOnce(new Error('所选周期暂无工作记录'))
  render(
    <MemoryRouter initialEntries={['/reports?kind=weekly&view=all&date=2026-10-26']}>
      <ReportsPage />
    </MemoryRouter>,
  )
  expect(screen.getByText('汇报周期')).toBeTruthy()
  expect(screen.getByRole('status').textContent).toBe('2026-10-26 — 2026-11-01（周一至周日）')
  fireEvent.click(screen.getByRole('button', { name: '生成周报' }))
  await screen.findByRole('alert')
  expect(generateReport).toHaveBeenLastCalledWith(
    { kind: 'weekly', date: '2026-10-26' },
    expect.any(String),
  )

  fireEvent.click(screen.getByRole('button', { name: '本周' }))
  expect(screen.queryByRole('alert')).toBeNull()
  expect(screen.getByRole('status').textContent).toBe('2026-10-19 — 2026-10-25（周一至周日）')
  vi.mocked(generateReport).mockResolvedValue({ reportId: 'report', jobId: 'job' })
  fireEvent.click(screen.getByRole('button', { name: '生成周报' }))
  await waitFor(() => expect(generateReport).toHaveBeenCalledTimes(2))
  expect(generateReport).toHaveBeenLastCalledWith(
    { kind: 'weekly', date: '2026-10-23' },
    expect.any(String),
  )
  expect(screen.queryByRole('button', { name: '上周' })).toBeNull()
  fireEvent.change(screen.getByLabelText('选择周报所在周'), { target: { value: '2026-10-16' } })
  expect(screen.getByRole('status').textContent).toBe('2026-10-12 — 2026-10-18（周一至周日）')
  fireEvent.change(screen.getByLabelText('选择周报所在周'), { target: { value: '2027-01-01' } })
  expect(screen.getByRole('status').textContent).toBe('2026-12-28 — 2027-01-03（周一至周日）')

  expect(screen.queryByRole('button', { name: '日报' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '生成周报' }))
  await waitFor(() => expect(generateReport).toHaveBeenCalledTimes(3))
  expect(generateReport).toHaveBeenLastCalledWith(
    { kind: 'weekly', date: '2027-01-01' },
    expect.any(String),
  )
})

it('clears period errors on reporting week changes and ignores a late failure from a different period', async () => {
  let rejectGeneration: (reason: Error) => void = () => {}
  vi.mocked(generateReport).mockImplementationOnce(
    () =>
      new Promise((_resolve, reject) => {
        rejectGeneration = reject
      }),
  )
  render(
    <MemoryRouter initialEntries={['/reports?kind=weekly&view=all&date=2026-10-26']}>
      <ReportsPage />
    </MemoryRouter>,
  )
  fireEvent.click(screen.getByRole('button', { name: '生成周报' }))
  fireEvent.change(screen.getByLabelText('选择周报所在周'), { target: { value: '2026-10-12' } })
  rejectGeneration(new Error('旧周报周期没有来源'))
  await waitFor(() =>
    expect(screen.getByRole('button', { name: '生成周报' })).toHaveProperty('disabled', false),
  )
  expect(screen.queryByRole('alert')).toBeNull()

  vi.mocked(generateReport).mockRejectedValueOnce(new Error('周报周期没有来源'))
  fireEvent.click(screen.getByRole('button', { name: '生成周报' }))
  await screen.findByRole('alert')
  fireEvent.change(screen.getByLabelText('选择周报所在周'), { target: { value: '2026-10-19' } })
  expect(screen.queryByRole('alert')).toBeNull()
})

it('keeps generation errors outside the page and clears them on dismissal, timeout, and another attempt', async () => {
  vi.useFakeTimers()
  vi.mocked(generateReport).mockRejectedValue(new Error('当前周期暂无工作记录'))
  const { container } = render(
    <MemoryRouter initialEntries={['/reports?kind=weekly&view=all&date=2026-10-23']}>
      <ReportsPage />
    </MemoryRouter>,
  )
  const generate = screen.getByRole('button', { name: '生成周报' })
  await act(async () => fireEvent.click(generate))
  expect(screen.getByRole('alert')).toBeTruthy()
  expect(container.querySelector('[role="alert"]')).toBeNull()
  expect(screen.queryByRole('button', { name: '重试' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '关闭提示' }))
  expect(screen.queryByRole('alert')).toBeNull()

  await act(async () => fireEvent.click(generate))
  await act(async () => vi.advanceTimersByTime(10000))
  expect(screen.queryByRole('alert')).toBeNull()

  await act(async () => fireEvent.click(generate))
  expect(screen.getByRole('alert')).toBeTruthy()
  vi.mocked(generateReport).mockResolvedValueOnce({ reportId: 'report', jobId: 'job' })
  await act(async () => fireEvent.click(generate))
  expect(screen.queryByRole('alert')).toBeNull()
})

it('redirects legacy daily list selection with a retirement notice', () => {
  render(
    <MemoryRouter initialEntries={['/reports?kind=daily&view=all']}>
      <ReportsPage />
    </MemoryRouter>,
  )
  expect(screen.getByText('正式日报已取消，现显示周报。')).toBeTruthy()
  expect(screen.getByRole('button', { name: '生成周报' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: '日报' })).toBeNull()
})
