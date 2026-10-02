import layoutStyles from '../../../../styles/layout.module.css'
import controlsStyles from '../../../../styles/controls.module.css'
import recordLayoutStyles from '../../../../styles/patterns/RecordLayout.module.css'
import styles from './WorkOverview.module.css'
import type { Work } from '@paa/api-contracts'
import { Actions } from '@web/components/actions/Actions'
import { Status } from '@web/components/feedback/Status'
import { DeleteRecord } from '@web/features/records/components/DeleteRecord'
import { WorkEditor } from '@web/features/work/components/editor/WorkEditor'
import { dateLabel } from '@web/utils/date'
import { detailState } from '@web/utils/navigation'
import { ChevronRight, CircleCheck, CircleDashed, CircleAlert } from 'lucide-react'
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
    <div className={`${recordLayoutStyles['record-list']} ${styles.list}`}>
      <div
        className={`${recordLayoutStyles['record-list-heading']} ${styles.columns}`}
        aria-hidden="true"
      >
        <span>工作事项</span>
        <span>状态</span>
        <span>最近更新</span>
        <span />
      </div>
      {items.map((work) => (
        <div
          className={`${recordLayoutStyles['record-row']} ${recordLayoutStyles['work-row']} ${styles.row}`}
          key={work.id}
        >
          <span
            className={`${recordLayoutStyles['work-state-icon']} ${styles.state}`}
            data-status={work.status}
            aria-hidden="true"
          >
            {work.status === 'done' ? (
              <CircleCheck size={18} />
            ) : work.status === 'blocked' ? (
              <CircleAlert size={18} />
            ) : (
              <CircleDashed size={18} />
            )}
          </span>
          <Link
            className={`${recordLayoutStyles['record-main']} ${styles.main}`}
            to={`/work/${work.id}${work.historical ? `?revision=${work.revision}` : ''}`}
            state={detailState(location)}
          >
            <div
              className={`${layoutStyles['row-between']} ${recordLayoutStyles['slot-row-between']}`}
            >
              <h3>{work.title}</h3>
            </div>
            <p className={`${recordLayoutStyles['record-summary']} ${styles.summary}`}>
              {work.bodyText || work.summary || '尚未补充工作内容'}
            </p>
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
          <span className={`${recordLayoutStyles['work-status']} ${styles.status}`}>
            <Status value={work.status} />
          </span>
          <time className={`${recordLayoutStyles['record-updated']} ${styles.updated}`}>
            {dateLabel(work.updatedAt)}
          </time>
          {own ? (
            <Actions className={`${recordLayoutStyles['record-actions']} ${styles.actions}`}>
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
            <ChevronRight size={18} className={styles.actions} />
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
