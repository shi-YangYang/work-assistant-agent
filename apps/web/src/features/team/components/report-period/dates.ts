import { customRangeError } from '@web/utils/date-range'

export type ReportKind = 'daily' | 'weekly'
export type Period = { start: string; end: string }

export function shiftDate(value: string, days: number) {
  const date = new Date(`${value}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + days)
  if (!Number.isFinite(date.getTime())) return ''
  const result = date.toISOString().slice(0, 10)
  return customRangeError(result, result) ? '' : result
}

export function reportPeriod(date: string, kind: ReportKind): Period {
  if (kind === 'daily') return { start: date, end: date }
  const weekday = new Date(`${date}T00:00:00Z`).getUTCDay()
  const start = shiftDate(date, -((weekday + 6) % 7))
  return { start, end: shiftDate(start, 6) }
}

export function selectedPeriod(params: URLSearchParams, kind: ReportKind, today: string) {
  const period = params.get('period') || (kind === 'daily' ? 'today' : 'this_week')
  if (period === 'custom') return { start: params.get('start') || '', end: params.get('end') || '' }
  if (period === 'this_month') {
    const start = `${today.slice(0, 7)}-01`
    return { start, end: shiftDate(shiftMonth(start, 1), -1) }
  }
  return reportPeriod(today, period === 'this_week' || kind === 'weekly' ? 'weekly' : 'daily')
}

export function shiftMonth(value: string, months: number) {
  const date = new Date(`${value.slice(0, 7)}-01T00:00:00Z`)
  date.setUTCMonth(date.getUTCMonth() + months)
  const result = date.toISOString().slice(0, 10)
  return customRangeError(result, result) ? '' : result
}

export function isSinglePeriod(period: Period, kind: ReportKind) {
  if (customRangeError(period.start, period.end)) return false
  const expected = reportPeriod(period.start, kind)
  return period.start === expected.start && period.end === expected.end
}

export function periodLabel(period: Period, kind: ReportKind, today: string) {
  if (customRangeError(period.start, period.end)) return '选择日期'
  const current = reportPeriod(today, kind)
  const previous = reportPeriod(shiftDate(today, kind === 'daily' ? -1 : -7), kind)
  const same = (other: Period) => period.start === other.start && period.end === other.end
  const prefix = same(current)
    ? kind === 'daily'
      ? '今天'
      : '本周'
    : same(previous)
      ? kind === 'daily'
        ? '昨天'
        : '上周'
      : ''
  const year =
    period.start.slice(0, 4) !== today.slice(0, 4) || period.end.slice(0, 4) !== today.slice(0, 4)
  const format = (value: string) =>
    `${year ? `${Number(value.slice(0, 4))}年` : ''}${Number(value.slice(5, 7))}月${Number(value.slice(8, 10))}日`
  const dates =
    period.start === period.end
      ? format(period.start)
      : `${format(period.start)}–${period.start.slice(0, 7) === period.end.slice(0, 7) ? `${Number(period.end.slice(8))}日` : format(period.end)}`
  return `${prefix ? `${prefix} · ` : ''}${dates}`
}
