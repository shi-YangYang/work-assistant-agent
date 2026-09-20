import type { DateRange } from '@paa/api-contracts'
import { timezoneLabel } from '@web/utils/timezones'

export function PeriodFilter({
  params,
  range,
  change,
}: {
  params: URLSearchParams
  range?: DateRange
  change: (values: Record<string, string>) => void
}) {
  const period = params.get('period') || 'this_week'
  return (
    <>
      <div className="period-filter">
        <select
          aria-label="日期范围"
          value={period}
          onChange={(e) =>
            change({ period: e.target.value, start: range?.start || '', end: range?.end || '' })
          }
        >
          <option value="today">今天</option>
          <option value="this_week">本周</option>
          <option value="this_month">本月</option>
          <option value="custom">自定义</option>
        </select>
        {period === 'custom' && (
          <div className="team-date-range">
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
                value={params.get('start') || ''}
                max={params.get('end') || undefined}
                onChange={(e) => change({ start: e.target.value })}
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
                value={params.get('end') || ''}
                min={params.get('start') || undefined}
                onChange={(e) => change({ end: e.target.value })}
              />
            </label>
          </div>
        )}
      </div>
      {range && (
        <p className="period-caption">
          {range.start} — {range.end} · {timezoneLabel(range.timezone)}
        </p>
      )}
    </>
  )
}
