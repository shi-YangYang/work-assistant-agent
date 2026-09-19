import { timezoneLabel } from './timezones'
import type { DateRange } from '@paa/api-contracts'
import { useState, type ReactNode } from 'react'
import { Search } from 'lucide-react'
import { SearchInput } from './SearchInput'

export function RecordEmpty({
  icon,
  title,
  children,
  action,
}: {
  icon: ReactNode
  title: string
  children: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="record-empty">
      <span className="record-empty-icon" aria-hidden="true">
        {icon}
      </span>
      <h3>{title}</h3>
      <p>{children}</p>
      {action && <div className="record-empty-actions">{action}</div>}
    </div>
  )
}

export function Pagination({
  page,
  hasNext,
  previous,
  next,
}: {
  page: number
  hasNext: boolean
  previous: () => void
  next: () => void
}) {
  return (
    <nav className="list-pagination" aria-label="列表分页">
      <button disabled={page === 1} onClick={previous}>
        上一页
      </button>
      <span>第 {page} 页</span>
      <button disabled={!hasNext} onClick={next}>
        下一页
      </button>
    </nav>
  )
}
export function WorkFilters({
  query,
  status,
  change,
}: {
  query: string
  status: string
  change: (values: Record<string, string>) => void
}) {
  const [resetKey, resetSearch] = useState(0)
  return (
    <div className="filters work-filters">
      <div className="work-search">
        <Search size={17} aria-hidden="true" />
        <SearchInput
          aria-label="搜索工作"
          placeholder="搜索标题、摘要、阻碍或下一步"
          value={query}
          onSearch={(q) => change({ q })}
          resetKey={resetKey}
        />
      </div>
      <select
        aria-label="工作状态"
        value={status}
        onChange={(e) => change({ status: e.target.value })}
      >
        <option value="">全部状态</option>
        <option value="in_progress">进行中</option>
        <option value="blocked">有阻碍</option>
        <option value="done">已完成</option>
      </select>
      {(query || status) && (
        <button
          className="text-button"
          onClick={() => {
            resetSearch((value) => value + 1)
            change({ q: '', status: '' })
          }}
        >
          清除筛选
        </button>
      )}
    </div>
  )
}
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
