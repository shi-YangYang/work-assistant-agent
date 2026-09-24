import utilitiesStyles from '../styles/utilities.module.css'
import noticeStyles from './Notice.module.css'
import { ApiError } from '@web/api/client'
import { useRetryWait } from '@web/hooks/useRetryWait'
import { captureDiagnostics, copyText, diagnosticText } from '@web/lib/diagnostics'
import { ErrorDiagnostics, SupportLink } from '@web/lib/support-link'
import type { ReactNode } from 'react'
import { useContext, useMemo, useState } from 'react'
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
  const [copied, setCopied] = useState('')
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
      {diagnostics && failure?.requestId && (
        <small className={noticeStyles['request-id']}>请求编号：{failure.requestId}</small>
      )}
      {(canRetry || diagnostics) && (
        <div className={`${noticeStyles['notice-actions']} ${actionsClassName}`}>
          {canRetry && (
            <button type="button" disabled={wait > 0} onClick={retry}>
              {wait ? `${wait} 秒后重试` : '重试'}
            </button>
          )}
          {diagnostics && (
            <>
              {supportLink && (
                <Link to={supportLink} state={{ diagnostics }}>
                  问题反馈
                </Link>
              )}
              <button
                type="button"
                onClick={() =>
                  void copyText(diagnosticText(diagnostics)).then(
                    () => setCopied('已复制诊断摘要'),
                    () => setCopied('复制失败，请打开问题反馈查看并选择摘要。'),
                  )
                }
              >
                复制诊断摘要
              </button>
            </>
          )}
        </div>
      )}
      {diagnostics && copied && <small role="status">{copied}</small>}
    </div>
  )
}
