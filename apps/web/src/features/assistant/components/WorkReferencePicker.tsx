import type { Work } from '@paa/api-contracts'
import { useState } from 'react'
import { Search, Check } from 'lucide-react'
import { Modal } from '@web/components/Modal'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Status } from '@web/components/Status'
import { usePagedResource } from '@web/hooks/usePagedResource'
import { referenceWorksPath } from '../api/requests'
import styles from './WorkReference.module.css'

export function WorkReferencePicker({
  selected,
  onClose,
  onSelect,
}: {
  selected?: string
  onClose: () => void
  onSelect: (work: Work) => void
}) {
  const [query, setQuery] = useState('')
  const list = usePagedResource<Work>(referenceWorksPath(query), 'updatedAt', 30000)
  return (
    <Modal title="引用工作" className={styles.picker} onClose={onClose}>
      <label className={styles.search}>
        <Search size={17} aria-hidden="true" />
        <input
          autoFocus
          aria-label="搜索工作"
          placeholder="搜索工作标题、描述或下一步"
          maxLength={200}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      <ErrorNotice retry={list.refresh}>{list.error}</ErrorNotice>
      <div className={styles.results} aria-busy={list.loading}>
        {list.data?.items.map((work) => (
          <button
            type="button"
            key={work.id}
            className={styles.option}
            aria-label={`引用 ${work.title}`}
            aria-pressed={selected === work.id}
            onClick={() => onSelect(work)}
          >
            <span>{work.title}</span>
            <Status value={work.status} />
            {selected === work.id && <Check size={15} aria-hidden="true" />}
          </button>
        ))}
        {!list.error && !list.loading && list.data && !list.data.items.length && (
          <p className={styles.empty}>{query ? '没有匹配的工作' : '还没有工作可引用'}</p>
        )}
        {list.loading && !list.data && (
          <p className={styles.empty} role="status">
            正在加载工作…
          </p>
        )}
      </div>
      {list.data?.nextCursor && (
        <button
          type="button"
          className={styles.more}
          disabled={list.loading}
          onClick={() => void list.loadMore()}
        >
          {list.loading ? '加载中…' : '加载更多'}
        </button>
      )}
    </Modal>
  )
}
