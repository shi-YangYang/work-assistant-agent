import searchInputStyles from '../../../styles/patterns/SearchInput.module.css'
import teamStyles from '../styles/team.module.css'
import type { TeamWorkspacePage } from '@paa/api-contracts'
import { PeriodFilter } from '@web/components/forms/PeriodFilter'
import { SearchInput } from '@web/components/forms/SearchInput'
import { type TeamRow as Row } from '@web/features/team/types'
import { useState } from 'react'
import { Search, SlidersHorizontal } from 'lucide-react'

export function TeamFilters({
  params,
  update,
  searchReset,
  data,
  view,
  scope,
}: {
  params: URLSearchParams
  update: (values: Record<string, string>, reset?: boolean) => void
  searchReset: number
  data: TeamWorkspacePage<Row> | null
  view: 'reports' | 'work'
  scope: 'updated' | 'current'
}) {
  const [expanded, setExpanded] = useState(false)
  const statusKey = `${view}Status`
  const active =
    Number(!!params.get('member')) +
    Number(!!params.get('members') && params.get('members') !== 'active') +
    Number(!!params.get(statusKey))
  const statuses =
    view === 'reports'
      ? [
          ['', '全部汇报'],
          ['expected', '应提交'],
          ['submitted', '已提交'],
          ['pending', '未提交'],
          ['overdue', '已逾期'],
          ['cancelled', '已撤销'],
        ]
      : [
          ['', '全部工作'],
          ['in_progress', '未完成'],
          ['blocked', '有阻碍'],
          ['done', '已完成'],
        ]
  return (
    <div className={teamStyles['team-toolbar']}>
      <div className={`${searchInputStyles['work-search']} ${teamStyles['slot-work-search']}`}>
        <Search size={17} aria-hidden="true" />
        <SearchInput
          aria-label="搜索团队内容"
          placeholder="搜索员工或内容"
          value={params.get('q') || ''}
          maxLength={200}
          onSearch={(q) => update({ q })}
          resetKey={searchReset}
        />
      </div>
      <button
        className={teamStyles['filter-toggle']}
        aria-expanded={expanded}
        aria-controls="team-advanced-filters"
        onClick={() => setExpanded(!expanded)}
      >
        <SlidersHorizontal size={16} /> 筛选{active ? ` · ${active}` : ''}
      </button>
      {(view === 'reports' || scope === 'updated') && (
        <PeriodFilter
          className={teamStyles['team-period-filter']}
          captionClassName={teamStyles['team-period-caption']}
          params={params}
          range={data?.range}
          change={update}
        />
      )}
      <div
        id="team-advanced-filters"
        className={teamStyles['advanced-filters']}
        data-open={expanded}
      >
        <select
          aria-label="选择员工"
          value={params.get('member') || ''}
          onChange={(e) => update({ member: e.target.value })}
        >
          <option value="">全部员工</option>
          {data?.members.map((member) => (
            <option key={member.id} value={member.id}>
              {member.name}
            </option>
          ))}
        </select>
        <select
          aria-label="员工范围"
          value={params.get('members') || 'active'}
          onChange={(e) => update({ members: e.target.value, member: '' })}
        >
          <option value="active">在职员工</option>
          <option value="inactive">停用员工</option>
          <option value="all">全部员工</option>
        </select>
        <select
          className={teamStyles['mobile-status']}
          aria-label="状态筛选"
          value={params.get(statusKey) || ''}
          onChange={(event) => update({ [statusKey]: event.target.value })}
        >
          {statuses.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}
