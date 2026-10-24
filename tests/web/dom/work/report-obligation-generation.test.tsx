// @vitest-environment jsdom
import type { ReportObligation } from '@paa/api-contracts'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router'
import { afterEach, expect, it, vi } from 'vitest'
import { api, write } from '@web/api/client'
import { ReportObligations } from '@web/features/reports/components/overview/ReportObligations'

vi.mock('@web/api/client', async (load) => ({
  ...(await load<typeof import('@web/api/client')>()),
  api: vi.fn(),
  write: vi.fn(),
}))
afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})
const item: ReportObligation = {
  id: 'obligation',
  ownerId: 'owner',
  name: null,
  kind: 'weekly',
  period: '2026-10-19',
  periodEnd: '2026-10-25',
  timezone: 'Asia/Shanghai',
  deadlineAt: '2026-10-25T10:00:00Z',
  state: 'cancelled',
  submittedAt: null,
  reportId: null,
}
function Location() {
  return <p>{useLocation().pathname}</p>
}
function view(reportId: string | null = null, team = false) {
  vi.mocked(api).mockResolvedValue({
    items: [{ ...item, reportId }],
    counts: { expected: 0, submitted: 0, pending: 0, overdue: 0, cancelled: 1 },
    nextCursor: null,
  })
  return render(
    <MemoryRouter>
      <Location />
      <ReportObligations team={team} />
    </MemoryRouter>,
  )
}

it('generates from an existing obligation with no live report even after deletion', async () => {
  vi.mocked(write).mockResolvedValue({ reportId: 'replacement' })
  view()
  fireEvent.click(await screen.findByRole('button', { name: '生成周报' }))
  await screen.findByText('/reports/replacement')
  expect(write).toHaveBeenCalledExactlyOnceWith(
    '/report-obligations/obligation/prepare',
    {},
    'POST',
    expect.any(String),
  )
})

it('opens the current report instead of generating again regardless of old obligation state', async () => {
  view('replacement')
  const link = await screen.findByRole('link', { name: '打开报告' })
  expect(link.getAttribute('href')).toBe('/reports/replacement')
  expect(screen.queryByRole('button', { name: '生成周报' })).toBeNull()
  expect(write).not.toHaveBeenCalled()
})

it('never exposes personal generation in the team view', async () => {
  view(null, true)
  await waitFor(() => expect(screen.getByText('已撤销')).toBeTruthy())
  expect(screen.queryByRole('button', { name: '生成周报' })).toBeNull()
})
