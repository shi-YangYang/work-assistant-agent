import type { ReactNode } from 'react'

export function RecordEmpty({
  icon,
  title,
  children,
  action,
}: {
  icon: ReactNode
  title: string
  children: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="record-empty">
      <span className="record-empty-icon" aria-hidden="true">
        {icon}
      </span>
      <h3>{title}</h3>
      <p>{children}</p>
      {action && <div className="record-empty-actions">{action}</div>}
    </div>
  )
}
