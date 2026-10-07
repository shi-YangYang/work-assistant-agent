import searchStyles from '@web/styles/patterns/SearchInput.module.css'
import { ListToolbar } from '@web/components/layout/list-toolbar/ListToolbar'
import { Search, X } from 'lucide-react'
import styles from './MembersPage.module.css'
import controls from '@web/styles/controls.module.css'

export function MembersToolbar({
  query,
  change,
  total,
  matched,
}: {
  query: string
  change: (query: string) => void
  total?: number
  matched?: number
}) {
  return (
    <ListToolbar>
      <div className={searchStyles['work-search']}>
        <Search size={16} aria-hidden="true" />
        <input
          aria-label="搜索成员"
          placeholder="搜索姓名或账号"
          value={query}
          onChange={(event) => change(event.target.value)}
        />
        {query && (
          <button
            className={controls['icon-button']}
            aria-label="清除搜索"
            onClick={() => change('')}
          >
            <X size={15} />
          </button>
        )}
      </div>
      {total !== undefined && query.trim() && (
        <span className={styles.count} role="status">
          找到 {matched} 人，共 {total} 人
        </span>
      )}
    </ListToolbar>
  )
}
