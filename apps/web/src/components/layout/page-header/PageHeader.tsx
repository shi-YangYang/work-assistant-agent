import type { ReactNode } from 'react'
import styles from './PageHeader.module.css'

export function PageHeader({
  title,
  description,
  meta,
  actions,
  context = 'page',
  placement = 'beside',
  className = '',
}: {
  title: ReactNode
  description?: ReactNode
  meta?: ReactNode
  actions?: ReactNode
  context?: 'page' | 'detail' | 'embedded'
  placement?: 'beside' | 'below'
  className?: string
}) {
  return (
    <header
      className={`${styles.header} ${className}`}
      data-layout-context={context}
      data-placement={placement}
    >
      <div className={styles.heading}>
        <div className={styles.title}>
          <h2>{title}</h2>
          {meta && <span className={styles.meta}>{meta}</span>}
        </div>
        {description && <div className={styles.description}>{description}</div>}
      </div>
      {actions && <div className={styles.actions}>{actions}</div>}
    </header>
  )
}
