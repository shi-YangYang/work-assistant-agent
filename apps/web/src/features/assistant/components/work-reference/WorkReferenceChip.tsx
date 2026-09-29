import type { WorkReferenceView } from '@paa/api-contracts'
import { BriefcaseBusiness, X } from 'lucide-react'
import { Link } from 'react-router'
import styles from './WorkReference.module.css'

export function WorkReferenceChip({
  reference,
  onRemove,
  disabled,
  linked = false,
}: {
  reference: WorkReferenceView
  onRemove?: () => void
  disabled?: boolean
  linked?: boolean
}) {
  const title = reference.unavailable ? '工作不可用' : (reference.title ?? '引用工作')
  return (
    <div className={styles.chip} data-unavailable={!!reference.unavailable} data-sent={linked}>
      <BriefcaseBusiness size={14} aria-hidden="true" />
      {linked && !reference.unavailable ? (
        <Link to={`/work/${encodeURIComponent(reference.workId)}`} title={title}>
          {title}
        </Link>
      ) : (
        <span title={title}>{title}</span>
      )}
      {onRemove && (
        <button type="button" aria-label="移除工作引用" disabled={disabled} onClick={onRemove}>
          <X size={14} />
        </button>
      )}
    </div>
  )
}
