import type { TeamWorkspacePage } from '@paa/api-contracts'
import { PeriodFilter } from '@web/components/PeriodFilter'
import { SearchInput } from '@web/components/SearchInput'
import { type TeamRow as Row } from '@web/features/team/types'
import { Search } from 'lucide-react'

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
  return (
    <div className="team-toolbar">
      <div className="work-search">
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
      {(view === 'reports' || scope === 'updated') && (
        <PeriodFilter params={params} range={data?.range} change={update} />
      )}
    </div>
  )
}
