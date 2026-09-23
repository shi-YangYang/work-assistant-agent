import styles from './PeriodFilter.module.css'
import formFieldStyles from './FormField.module.css'
import type { DateRange } from '@paa/api-contracts'
import { todayIn } from '@web/utils/date'
import { customRangeError } from '@web/utils/date-range'
import { timezoneLabel } from '@web/utils/timezones'
import { useId, useState } from 'react'

export function PeriodFilter({
  params,
  range,
  change,
  className = '',
  captionClassName = '',
}: {
  className?: string
  captionClassName?: string
  params: URLSearchParams
  range?: DateRange
  change: (values: Record<string, string>) => void
}) {
  const period = params.get('period') || 'this_week'
  const start = params.get('start') || ''
  const end = params.get('end') || ''
  const key = `${period}:${start}:${end}`
  const [draft, setDraft] = useState({ key, start, end })
  if (draft.key !== key) setDraft({ key, start, end })
  const errorId = useId()
  const error = period === 'custom' ? customRangeError(draft.start, draft.end) : ''
  const editDate = (field: 'start' | 'end', value: string) => {
    const next = { ...draft, [field]: value }
    setDraft(next)
    if (!customRangeError(next.start, next.end)) change({ start: next.start, end: next.end })
  }
  return (
    <>
      <div className={`${styles['period-filter']} ${className}`}>
        <select
          aria-label="日期范围"
          value={period}
          onChange={(e) => {
            if (e.target.value !== 'custom') {
              change({ period: e.target.value, start: '', end: '' })
              return
            }
            const first = range?.start || todayIn(range?.timezone ?? 'Asia/Shanghai')
            const last = range?.end || first
            change({ period: 'custom', start: first, end: last })
          }}
        >
          <option value="today">今天</option>
          <option value="this_week">本周</option>
          <option value="this_month">本月</option>
          <option value="custom">自定义</option>
        </select>
        {period === 'custom' && (
          <div className={styles['team-date-range']}>
            <label>
              开始日期
              <input
                type="date"
                onClick={(e) => {
                  try {
                    e.currentTarget.showPicker?.()
                  } catch {
                    /* Native picker unavailable. */
                  }
                }}
                value={draft.start}
                min="0001-01-01"
                max={draft.end || '9999-12-30'}
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? errorId : undefined}
                onChange={(e) => editDate('start', e.target.value)}
              />
            </label>
            <span>至</span>
            <label>
              结束日期
              <input
                type="date"
                onClick={(e) => {
                  try {
                    e.currentTarget.showPicker?.()
                  } catch {
                    /* Native picker unavailable. */
                  }
                }}
                value={draft.end}
                min={draft.start || '0001-01-01'}
                max="9999-12-30"
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? errorId : undefined}
                onChange={(e) => editDate('end', e.target.value)}
              />
            </label>
          </div>
        )}
      </div>
      {error && (
        <small className={formFieldStyles['form-field-error']} id={errorId} role="alert">
          {error}，筛选尚未更新。
        </small>
      )}
      {range && (
        <p className={`${styles['period-caption']} ${captionClassName}`}>
          {range.start} — {range.end} · {timezoneLabel(range.timezone)}
        </p>
      )}
    </>
  )
}
