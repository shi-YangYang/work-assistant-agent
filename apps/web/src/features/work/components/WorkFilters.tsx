import { SearchInput } from '@web/components/SearchInput'
import { Search } from 'lucide-react'
import { useState } from 'react'

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
