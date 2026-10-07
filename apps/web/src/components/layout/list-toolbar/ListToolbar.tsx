import type { ReactNode } from 'react'
import styles from './ListToolbar.module.css'

export function ListToolbar({
  children,
  actions,
  className = '',
}: {
  children: ReactNode
  actions?: ReactNode
  className?: string
}) {
  return (
    <div className={`${styles.toolbar} ${className}`}>
      <div className={styles.filters}>{children}</div>
      {actions && <div className={styles.actions}>{actions}</div>}
    </div>
  )
}
