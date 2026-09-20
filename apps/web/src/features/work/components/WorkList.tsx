import type { Work } from '@paa/api-contracts'
import { Actions } from '@web/components/Actions'
import { Status } from '@web/components/Status'
import { DeleteRecord } from '@web/features/records/components/DeleteRecord'
import { WorkEditor } from '@web/features/work/components/WorkEditor'
import { dateLabel } from '@web/utils/date'
import { detailState } from '@web/utils/navigation'
import { ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { Link, useLocation } from 'react-router'

export function WorkList({
  items,
  own = false,
  refresh,
}: {
  items: Work[]
  own?: boolean
  refresh: () => void
}) {
  const [editing, setEditing] = useState<Work | null>(null)
  const [deleting, setDeleting] = useState<Work | null>(null)
  const location = useLocation()
  return (
    <div className="record-list">
      {items.map((work) => (
        <div className="record-row work-row" key={work.id}>
          <Link
            className="record-main"
            to={`/work/${work.id}${work.historical ? `?revision=${work.revision}` : ''}`}
            state={detailState(location)}
          >
            <div className="row-between">
              <h3>{work.title}</h3>
              <Status value={work.status} />
            </div>
            <p className="record-summary">{work.summary}</p>
            {work.dueDate && <small className="record-note">截止 {work.dueDate}</small>}
            {(work.blocker || work.nextStep) && (
              <small className={`record-note ${work.blocker ? 'work-blocker' : ''}`}>
                {work.blocker ? `阻碍：${work.blocker}` : `下一步：${work.nextStep}`}
              </small>
            )}
          </Link>
          <time className="record-updated">{dateLabel(work.updatedAt)}</time>
          {own ? (
            <Actions>
              <button role="menuitem" onClick={() => setEditing(work)}>
                编辑工作
              </button>
              <button role="menuitem" className="danger" onClick={() => setDeleting(work)}>
                删除工作
              </button>
            </Actions>
          ) : (
            <ChevronRight size={18} />
          )}
        </div>
      ))}
      {deleting && (
        <DeleteRecord
          kind="work-items"
          id={deleting.id}
          title={deleting.title}
          revision={deleting.revision}
          onClose={() => setDeleting(null)}
          onDeleted={() => {
            setDeleting(null)
            refresh()
          }}
        />
      )}
      {editing && (
        <WorkEditor
          work={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            refresh()
          }}
        />
      )}
    </div>
  )
}
