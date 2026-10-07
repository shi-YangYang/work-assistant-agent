import { ListToolbar } from '@web/components/layout/list-toolbar/ListToolbar'
import controlsStyles from '../../../../styles/controls.module.css'
import searchInputStyles from '../../../../styles/patterns/SearchInput.module.css'
import styles from './WorkFilters.module.css'
import { SearchInput } from '@web/components/forms/SearchInput'
import { Search } from 'lucide-react'
import { useState } from 'react'

export function WorkFilters({
  compact = false,
  query,
  status,
  change,
}: {
  compact?: boolean
  query: string
  status: string
  change: (values: Record<string, string>) => void
}) {
  const [resetKey, resetSearch] = useState(0)
  return (
    <ListToolbar className={`${styles['work-filters']} ${compact ? styles.compact : ''}`}>
      <div className={searchInputStyles['work-search']}>
        <Search size={17} aria-hidden="true" />
        <SearchInput
          aria-label="搜索工作"
          placeholder="搜索工作…"
          title="搜索工作标题、正文或进展"
          value={query}
          maxLength={200}
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
          className={`${controlsStyles['text-button']}`}
          onClick={() => {
            resetSearch((value) => value + 1)
            change({ q: '', status: '' })
          }}
        >
          清除筛选
        </button>
      )}
    </ListToolbar>
  )
}
