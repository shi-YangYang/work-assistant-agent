import styles from './RecordEmpty.module.css'
import type { ReactNode } from 'react'

export function RecordEmpty({
  icon,
  title,
  children,
  action,
  className = '',
}: {
  className?: string
  icon: ReactNode
  title: string
  children: ReactNode
  action?: ReactNode
}) {
  return (
    <div className={`${styles['record-empty']} ${className}`}>
      <span className={styles['record-empty-icon']} aria-hidden="true">
        {icon}
      </span>
      <h3>{title}</h3>
      <p>{children}</p>
      {action && <div className={styles['record-empty-actions']}>{action}</div>}
    </div>
  )
}
