import styles from './PanelSection.module.css'
import { ChevronDown } from 'lucide-react'
import type { ReactNode } from 'react'
import { useId } from 'react'

export function PanelSection({
  title,
  status,
  defaultOpen = false,
  children,
  compactStatus = false,
  separated = false,
  bodyClassName = '',
}: {
  title: string
  status?: ReactNode
  defaultOpen?: boolean
  children: ReactNode
  compactStatus?: boolean
  separated?: boolean
  bodyClassName?: string
}) {
  const id = useId()
  return (
    <details
      className={styles['panel-section']}
      data-compact-status={compactStatus}
      data-separated={separated}
      open={defaultOpen}
      onInvalidCapture={(event) => {
        // Reveal invalid fields before native form validation tries to focus them.
        event.currentTarget.open = true
      }}
    >
      <summary>
        <h3 id={id}>{title}</h3>
        {status && <span className={styles['panel-section-status']}>{status}</span>}
        <ChevronDown size={18} className={styles['panel-section-chevron']} aria-hidden="true" />
      </summary>
      <div
        className={`${styles['panel-section-body']} ${bodyClassName}`}
        role="region"
        aria-labelledby={id}
      >
        {children}
      </div>
    </details>
  )
}
