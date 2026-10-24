import { useState } from 'react'
import { createPortal } from 'react-dom'
import type { DateRange } from '@paa/api-contracts'
import { ChevronDown, ChevronLeft, ChevronRight, X } from 'lucide-react'
import { usePopover } from '@web/components/overlays/usePopover'
import { todayIn } from '@web/utils/date'
import { customRangeError } from '@web/utils/date-range'
import { timezoneLabel } from '@web/utils/timezones'
import { ReportCalendar } from './ReportCalendar'
import {
  isSinglePeriod,
  periodLabel,
  reportPeriod,
  selectedPeriod,
  shiftDate,
  type ReportKind,
} from './dates'
import styles from './report-period.module.css'

export function ReportPeriodPicker({
  params,
  kind,
  range,
  change,
}: {
  params: URLSearchParams
  kind: ReportKind
  range?: DateRange
  change: (values: Record<string, string>) => void
}) {
  const [timezone, setTimezone] = useState(range?.timezone)
  if (range?.timezone && range.timezone !== timezone) setTimezone(range.timezone)
  const today = timezone ? todayIn(timezone) : ''
  const selected = today ? selectedPeriod(params, kind, today) : { start: '', end: '' }
  const single = isSinglePeriod(selected, kind)
  const scopeKey = `${kind}:${params.get('period')}:${selected.start}:${selected.end}`
  const popover = usePopover({ placement: 'bottom-start', disabled: !timezone, scopeKey })
  const apply = (values: Record<string, string>) => {
    popover.close()
    change(values)
  }
  const choose = (date: string) => {
    const period = reportPeriod(date, kind)
    if (customRangeError(period.start, period.end)) return
    apply({ period: 'custom', ...period })
  }
  const reset = () => apply({ period: 'this_week', start: '', end: '' })
  const unit = '周'
  const step = 7
  const canMove = (delta: number) => {
    const period = reportPeriod(shiftDate(selected.start, delta), kind)
    return single && !customRangeError(period.start, period.end)
  }
  return (
    <div className={styles.picker} aria-label="汇报周期">
      {single && (
        <button
          type="button"
          className={styles.arrow}
          aria-label={`前一${unit}`}
          disabled={!canMove(-step)}
          onClick={() => choose(shiftDate(selected.start, -step))}
        >
          <ChevronLeft size={16} />
        </button>
      )}
      <button
        type="button"
        {...popover.triggerProps}
        className={styles.trigger}
        disabled={!timezone}
        aria-haspopup="dialog"
        aria-label="选择汇报周期"
      >
        <span>
          {today ? `${single ? '' : '范围 · '}${periodLabel(selected, kind, today)}` : '本周'}
        </span>
        <ChevronDown size={14} />
      </button>
      {single && (
        <button
          type="button"
          className={styles.arrow}
          aria-label={`后一${unit}`}
          disabled={!canMove(step)}
          onClick={() => choose(shiftDate(selected.start, step))}
        >
          <ChevronRight size={16} />
        </button>
      )}
      {!single && today && (
        <button type="button" className={styles.return} onClick={reset}>
          {'回到本周'}
        </button>
      )}
      {popover.open &&
        createPortal(
          <div
            {...popover.panelProps}
            role="dialog"
            aria-label="选择汇报周期"
            className={styles.panel}
          >
            <header>
              <strong>{'选择周报周期'}</strong>
              <button type="button" aria-label="关闭日期选择" onClick={() => popover.close()}>
                <X size={16} />
              </button>
            </header>
            <div className={styles.shortcuts}>
              <button type="button" onClick={reset}>
                {'本周'}
              </button>
              <button type="button" onClick={() => choose(shiftDate(today, -step))}>
                {'上周'}
              </button>
            </div>
            <ReportCalendar kind={kind} selected={selected} today={today} choose={choose} />
            <details className={styles.more}>
              <summary>更多日期筛选</summary>
              <button
                type="button"
                onClick={() => apply({ period: 'this_month', start: '', end: '' })}
              >
                查看本月周报
              </button>
              <RangeForm
                start={selected.start}
                end={selected.end}
                weekly={kind === 'weekly'}
                apply={apply}
              />
            </details>
            <p className={styles.timezone}>
              按{timezoneLabel(timezone!)}计算{'，每周一至周日'}。
            </p>
          </div>,
          document.body,
        )}
    </div>
  )
}

function RangeForm({
  start,
  end,
  weekly,
  apply,
}: {
  start: string
  end: string
  weekly: boolean
  apply: (values: Record<string, string>) => void
}) {
  const [first, setFirst] = useState(start)
  const [last, setLast] = useState(end)
  const error = customRangeError(first, last)
  return (
    <form
      className={styles.range}
      onSubmit={(event) => {
        event.preventDefault()
        if (!error) apply({ period: 'custom', start: first, end: last })
      }}
    >
      <label>
        开始日期
        <input
          type="date"
          min="0001-01-01"
          max="9999-12-30"
          value={first}
          onChange={(e) => setFirst(e.target.value)}
        />
      </label>
      <label>
        结束日期
        <input
          type="date"
          min="0001-01-01"
          max="9999-12-30"
          value={last}
          onChange={(e) => setLast(e.target.value)}
        />
      </label>
      {error && <small role="alert">{error}</small>}
      {weekly && <small>查询与所选范围相交的完整周报。</small>}
      <button type="submit" disabled={!!error}>
        应用范围
      </button>
    </form>
  )
}
