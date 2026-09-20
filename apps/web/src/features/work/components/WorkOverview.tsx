import type { Work } from '@paa/api-contracts'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Pagination } from '@web/components/Pagination'
import { RecordEmpty } from '@web/components/RecordEmpty'
import { workListPath } from '@web/features/work/api/requests'
import { CreateWork } from '@web/features/work/components/CreateWork'
import { WorkFilters } from '@web/features/work/components/WorkFilters'
import { WorkList } from '@web/features/work/components/WorkList'
import { useCursorPage } from '@web/hooks/useCursorPage'
import { ChevronRight, ClipboardList, Plus, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'

export function WorkPage() {
  const [creating, setCreating] = useState(false)
  const [search] = useSearchParams()
  const query = search.get('q') ?? ''
  const status = search.get('status') ?? ''
  const list = useCursorPage<Work>(workListPath(query, status))
  return (
    <div className="page records-page work-page">
      <div className="page-heading">
        <h2>我的工作</h2>
        <div className="card-actions">
          <button
            className="icon-button"
            aria-label="刷新工作"
            title="刷新工作"
            onClick={list.refresh}
          >
            <RefreshCw size={16} />
          </button>
          <button className="primary" onClick={() => setCreating(true)}>
            <Plus size={16} />
            新建工作
          </button>
        </div>
      </div>
      {creating && (
        <CreateWork
          onClose={() => setCreating(false)}
          onSaved={() => {
            setCreating(false)
            list.refresh()
          }}
        />
      )}
      <div className="records-surface">
        <div className="records-toolbar">
          <WorkFilters query={query} status={status} change={list.filter} />
        </div>
        <ErrorNotice retry={list.refresh}>{list.error}</ErrorNotice>
        <div className="records-results" aria-label="工作列表">
          {!list.data && !list.error && (
            <p className="records-loading" role="status">
              正在读取工作…
            </p>
          )}
          {list.data &&
            (list.data.items.length ? (
              <WorkList items={list.data.items} own refresh={list.refresh} />
            ) : (
              <RecordEmpty
                icon={<ClipboardList size={27} />}
                title={query || status ? '没有符合条件的工作' : '还没有工作'}
                action={
                  query || status ? (
                    <button onClick={() => list.filter({ q: '', status: '' })}>重置筛选</button>
                  ) : (
                    <>
                      <button className="primary" onClick={() => setCreating(true)}>
                        <Plus size={16} />
                        创建第一项工作
                      </button>
                      <Link to="/assistant">
                        前往工作助手
                        <ChevronRight size={15} />
                      </Link>
                    </>
                  )
                }
              >
                {query || status
                  ? '换个关键词，或清除筛选条件。'
                  : '记录一项工作，随时跟进进展与下一步。'}
              </RecordEmpty>
            ))}
        </div>
        {list.data && (list.page > 1 || list.data.nextCursor) && (
          <Pagination
            page={list.page}
            hasNext={!!list.data.nextCursor}
            previous={list.previous}
            next={list.next}
          />
        )}
      </div>
    </div>
  )
}
