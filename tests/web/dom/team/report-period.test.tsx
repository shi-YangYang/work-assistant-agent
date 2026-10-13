// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ReportPeriodPicker } from '../../../../apps/web/src/features/team/components/report-period/ReportPeriodPicker'
import {
  isSinglePeriod,
  periodLabel,
  reportPeriod,
  shiftDate,
} from '../../../../apps/web/src/features/team/components/report-period/dates'
import type { ReportKind } from '../../../../apps/web/src/features/team/components/report-period/dates'
import type { DateRange } from '@paa/api-contracts'

const range: DateRange = {
  period: 'this_week',
  start: '2026-10-12',
  end: '2026-10-18',
  timezone: 'Asia/Shanghai',
}
function Example({
  kind = 'daily',
  query = '',
  timezone = 'Asia/Shanghai',
  onChange = vi.fn(),
}: {
  kind?: ReportKind
  query?: string
  timezone?: string
  onChange?: (values: Record<string, string>) => void
}) {
  const [params, setParams] = useState(new URLSearchParams(query))
  return (
    <ReportPeriodPicker
      params={params}
      kind={kind}
      range={{ ...range, timezone }}
      change={(values) => {
        onChange(values)
        setParams(new URLSearchParams(Object.entries(values).filter(([, value]) => value)))
      }}
    />
  )
}
const open = () => fireEvent.click(screen.getByRole('button', { name: '选择汇报周期' }))
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-10-13T04:00:00Z'))
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

it('browses company-local days without showing a second date caption and dismisses the mobile fallback', () => {
  const change = vi.fn()
  render(<Example timezone="America/Los_Angeles" onChange={change} />)
  expect(screen.getByRole('button', { name: '选择汇报周期' }).textContent).toBe('今天 · 10月12日')
  expect(screen.queryByText(/洛杉矶时间/)).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '前一天' }))
  expect(change).toHaveBeenLastCalledWith({
    period: 'custom',
    start: '2026-10-11',
    end: '2026-10-11',
  })
  open()
  expect(screen.getByRole('button', { name: '昨天' })).toBeTruthy()
  expect(screen.getByText(/洛杉矶时间/)).toBeTruthy()
  fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(document.activeElement).toBe(screen.getByRole('button', { name: '选择汇报周期' }))
  open()
  fireEvent.pointerDown(document.body)
  expect(screen.queryByRole('dialog')).toBeNull()
})

it('selects and highlights whole weeks, supports keyboard navigation, and offers no Today shortcut for weekly reports', async () => {
  const change = vi.fn()
  render(<Example kind="weekly" onChange={change} />)
  open()
  expect(screen.queryByRole('button', { name: '今天' })).toBeNull()
  expect(screen.getAllByRole('gridcell', { selected: true })).toHaveLength(7)
  fireEvent.keyDown(screen.getByRole('gridcell', { name: '2026-10-12，选择该周' }), {
    key: 'ArrowLeft',
  })
  await act(async () => new Promise((resolve) => requestAnimationFrame(() => resolve())))
  expect(document.activeElement?.getAttribute('data-date')).toBe('2026-10-11')
  fireEvent.click(screen.getByRole('gridcell', { name: '2026-10-11，选择该周' }))
  expect(change).toHaveBeenLastCalledWith({
    period: 'custom',
    start: '2026-10-05',
    end: '2026-10-11',
  })
  expect(screen.getByRole('button', { name: '选择汇报周期' }).textContent).toBe(
    '上周 · 10月5日–11日',
  )
  open()
  expect(screen.getAllByRole('gridcell', { selected: true })).toHaveLength(7)
  fireEvent.click(screen.getByRole('button', { name: '本周' }))
  expect(change).toHaveBeenLastCalledWith({ period: 'this_week', start: '', end: '' })
})

it('keeps month and custom ranges in more filters, rejects incomplete drafts, and can return to the current period', () => {
  const change = vi.fn()
  render(<Example kind="weekly" onChange={change} />)
  open()
  expect(screen.getByText('更多日期筛选').closest('details')!.open).toBe(false)
  screen.getByText('更多日期筛选').closest('details')!.open = true
  fireEvent.click(screen.getByRole('button', { name: '查看本月周报' }))
  expect(change).toHaveBeenLastCalledWith({ period: 'this_month', start: '', end: '' })
  expect(screen.getByRole('button', { name: '选择汇报周期' }).textContent).toBe(
    '范围 · 10月1日–31日',
  )
  expect(screen.queryByRole('button', { name: '前一周' })).toBeNull()
  open()
  screen.getByText('更多日期筛选').closest('details')!.open = true
  fireEvent.change(screen.getByLabelText('结束日期'), { target: { value: '' } })
  expect((screen.getByRole('button', { name: '应用范围' }) as HTMLButtonElement).disabled).toBe(
    true,
  )
  expect(change).toHaveBeenCalledTimes(1)
  fireEvent.change(screen.getByLabelText('开始日期'), { target: { value: '2026-09-01' } })
  fireEvent.change(screen.getByLabelText('结束日期'), { target: { value: '2026-09-30' } })
  fireEvent.click(screen.getByRole('button', { name: '应用范围' }))
  expect(change).toHaveBeenLastCalledWith({
    period: 'custom',
    start: '2026-09-01',
    end: '2026-09-30',
  })
  fireEvent.click(screen.getByRole('button', { name: '回到本周' }))
  expect(change).toHaveBeenLastCalledWith({ period: 'this_week', start: '', end: '' })
})

it('preserves the known company timezone while a new query loads and closes when the report kind changes', () => {
  const params = new URLSearchParams('period=today')
  const view = render(
    <ReportPeriodPicker params={params} kind="daily" range={range} change={vi.fn()} />,
  )
  open()
  view.rerender(
    <ReportPeriodPicker
      params={new URLSearchParams('period=this_week')}
      kind="weekly"
      change={vi.fn()}
    />,
  )
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(screen.getByRole('button', { name: '选择汇报周期' }).textContent).toBe(
    '本周 · 10月12日–18日',
  )
  expect((screen.getByRole('button', { name: '选择汇报周期' }) as HTMLButtonElement).disabled).toBe(
    false,
  )
})

it('handles leap dates, cross-year weeks and supported date boundaries', () => {
  expect(shiftDate('2024-03-01', -1)).toBe('2024-02-29')
  const week = reportPeriod('2027-01-01', 'weekly')
  expect(week).toEqual({ start: '2026-12-28', end: '2027-01-03' })
  expect(periodLabel(week, 'weekly', '2027-01-01')).toBe('本周 · 2026年12月28日–2027年1月3日')
  expect(isSinglePeriod(week, 'weekly')).toBe(true)
  expect(isSinglePeriod({ start: '2026-10-13', end: '2026-10-19' }, 'weekly')).toBe(false)
  expect(shiftDate('0001-01-01', -1)).toBe('')
  expect(shiftDate('9999-12-30', 1)).toBe('')
})
