import layoutStyles from '../../../styles/layout.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import recordLayoutStyles from '../../../components/RecordLayout.module.css'
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
    <div className={recordLayoutStyles['record-list']}>
      {items.map((work) => (
        <div
          className={`${recordLayoutStyles['record-row']} ${recordLayoutStyles['work-row']}`}
          key={work.id}
        >
          <Link
            className={recordLayoutStyles['record-main']}
            to={`/work/${work.id}${work.historical ? `?revision=${work.revision}` : ''}`}
            state={detailState(location)}
          >
            <div
              className={`${layoutStyles['row-between']} ${recordLayoutStyles['slot-row-between']}`}
            >
              <h3>{work.title}</h3>
              <Status value={work.status} />
            </div>
            <p className={recordLayoutStyles['record-summary']}>{work.summary}</p>
            {work.dueDate && (
              <small className={recordLayoutStyles['record-note']}>截止 {work.dueDate}</small>
            )}
            {(work.blocker || work.nextStep) && (
              <small
                className={`${recordLayoutStyles['record-note']} ${work.blocker ? recordLayoutStyles['work-blocker'] : ''}`}
              >
                {work.blocker ? `阻碍：${work.blocker}` : `下一步：${work.nextStep}`}
              </small>
            )}
          </Link>
          <time className={recordLayoutStyles['record-updated']}>{dateLabel(work.updatedAt)}</time>
          {own ? (
            <Actions className={recordLayoutStyles['record-actions']}>
              <button role="menuitem" onClick={() => setEditing(work)}>
                编辑工作
              </button>
              <button
                role="menuitem"
                className={controlsStyles['danger']}
                onClick={() => setDeleting(work)}
              >
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
