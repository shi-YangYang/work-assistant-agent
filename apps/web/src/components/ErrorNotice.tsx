import utilitiesStyles from '../styles/utilities.module.css'
import noticeStyles from './Notice.module.css'
import { ApiError } from '@web/api/client'
import { useRetryWait } from '@web/hooks/useRetryWait'
import { captureDiagnostics } from '@web/lib/diagnostics'
import { ErrorDiagnostics, SupportLink } from '@web/lib/support-link'
import type { ReactNode } from 'react'
import { useContext, useMemo } from 'react'
import { Link } from 'react-router'

export function ErrorNotice({
  children,
  retry,
  className = '',
  actionsClassName = '',
}: {
  children: ReactNode | Error
  className?: string
  actionsClassName?: string
  retry?: () => void
}) {
  const supportLink = useContext(SupportLink)
  const showDiagnostics = useContext(ErrorDiagnostics)
  const wait = useRetryWait(children)
  const failure = children instanceof ApiError ? children : null
  const diagnostics = useMemo(
    () => (showDiagnostics && children ? (failure?.diagnostics ?? captureDiagnostics()) : null),
    [showDiagnostics, children, failure],
  )
  if (!children || failure?.category === 'cancelled') return null
  const canRetry = retry && (!failure || failure.retryable)
  return (
    <div
      className={`${noticeStyles['notice']} ${utilitiesStyles['error'] + ' ' + noticeStyles['slot-error']} ${className}`}
      role="alert"
    >
      <span>{children instanceof Error ? children.message : children}</span>
      {(canRetry || (diagnostics && supportLink)) && (
        <div className={`${noticeStyles['notice-actions']} ${actionsClassName}`}>
          {canRetry && (
            <button type="button" disabled={wait > 0} onClick={retry}>
              {wait ? `${wait} 秒后重试` : '重试'}
            </button>
          )}
          {diagnostics && supportLink && (
            <Link to={supportLink} state={{ diagnostics }}>
              问题反馈
            </Link>
          )}
        </div>
      )}
    </div>
  )
}
