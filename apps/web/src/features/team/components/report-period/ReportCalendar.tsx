import { useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { customRangeError } from '@web/utils/date-range'
import { reportPeriod, shiftDate, shiftMonth, type Period, type ReportKind } from './dates'
import styles from './report-period.module.css'

export function ReportCalendar({
  kind,
  selected,
  today,
  choose,
}: {
  kind: ReportKind
  selected: Period
  today: string
  choose: (date: string) => void
}) {
  const initial = customRangeError(selected.start, selected.end) ? today : selected.start
  const [month, setMonth] = useState(initial.slice(0, 7))
  const [focused, setFocused] = useState(initial)
  const calendar = useRef<HTMLDivElement>(null)
  useEffect(() => {
    calendar.current
      ?.querySelector<HTMLButtonElement>('[tabindex="0"]')
      ?.focus({ preventScroll: true })
  }, [])
  const first = `${month}-01`
  const start = reportPeriod(first, 'weekly').start
  const focusDate = (date: string) => {
    if (!date) return
    setFocused(date)
    setMonth(date.slice(0, 7))
    requestAnimationFrame(() =>
      calendar.current?.querySelector<HTMLButtonElement>(`[data-date="${date}"]`)?.focus(),
    )
  }
  const moveMonth = (delta: number) => {
    const date = shiftMonth(first, delta)
    if (date) {
      setMonth(date.slice(0, 7))
      setFocused(date)
    }
  }
  return (
    <div className={styles.calendar} ref={calendar}>
      <div className={styles.month}>
        <button
          type="button"
          aria-label="上个月"
          disabled={!shiftMonth(first, -1)}
          onClick={() => moveMonth(-1)}
        >
          <ChevronLeft size={16} />
        </button>
        <input
          type="month"
          aria-label="日历月份"
          value={month}
          min="0001-01"
          max="9999-12"
          onChange={(event) => {
            const value = event.target.value
            if (!customRangeError(`${value}-01`, `${value}-01`)) {
              setMonth(value)
              setFocused(`${value}-01`)
            }
          }}
        />
        <button
          type="button"
          aria-label="下个月"
          disabled={!shiftMonth(first, 1)}
          onClick={() => moveMonth(1)}
        >
          <ChevronRight size={16} />
        </button>
      </div>
      <div role="grid" aria-label="选择一周">
        <div role="row" className={styles.week}>
          {['一', '二', '三', '四', '五', '六', '日'].map((day) => (
            <span role="columnheader" key={day}>
              {day}
            </span>
          ))}
        </div>
        {Array.from({ length: 6 }, (_, row) => (
          <div role="row" className={`${styles.week} ${styles.weekChoice}`} key={row}>
            {Array.from({ length: 7 }, (_, column) => {
              const date = shiftDate(start, row * 7 + column)
              const period = reportPeriod(date, kind)
              const disabled = !date || !!customRangeError(period.start, period.end)
              return (
                <button
                  type="button"
                  role="gridcell"
                  key={column}
                  data-date={date}
                  disabled={disabled}
                  aria-label={date ? `${date}${'，选择该周'}` : '不可选日期'}
                  aria-selected={!disabled && date >= selected.start && date <= selected.end}
                  aria-current={date === today ? 'date' : undefined}
                  data-outside={date.slice(0, 7) !== month}
                  tabIndex={date === focused ? 0 : -1}
                  onClick={() => choose(date)}
                  onKeyDown={(event) => {
                    const delta = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[
                      event.key
                    ]
                    const target =
                      delta !== undefined
                        ? shiftDate(date, delta)
                        : event.key === 'Home'
                          ? reportPeriod(date, 'weekly').start
                          : event.key === 'End'
                            ? reportPeriod(date, 'weekly').end
                            : event.key === 'PageUp'
                              ? shiftMonth(date, -1)
                              : event.key === 'PageDown'
                                ? shiftMonth(date, 1)
                                : ''
                    if (target) {
                      event.preventDefault()
                      focusDate(target)
                    }
                  }}
                >
                  {date ? Number(date.slice(8)) : ''}
                </button>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}
