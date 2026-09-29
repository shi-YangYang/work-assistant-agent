import utilitiesStyles from '../styles/utilities.module.css'
import noticeStyles from './Notice.module.css'
import { ApiError } from '@web/api/client'
import { useRetryWait } from '@web/hooks/useRetryWait'
import { captureDiagnostics } from '@web/lib/diagnostics'
import { ErrorDiagnostics, SupportLink } from '@web/lib/support-link'
import { ErrorNoticeContext, type NoticeContent } from '@web/lib/error-notices'
import { useContext, useId, useLayoutEffect, useMemo } from 'react'
import { Link } from 'react-router'

export function ErrorNotice(props: NoticeContent) {
  const context = useContext(ErrorNoticeContext)
  const store = context?.store
  const scope = context?.scope
  const id = useId()
  const diagnostics = useContext(ErrorDiagnostics)
  const supportLink = useContext(SupportLink)
  const { children, retry, retryLabel, hint, className, actionsClassName, priority } = props
  useLayoutEffect(() => {
    if (!store || !scope) return
    if (!children || (children instanceof ApiError && children.category === 'cancelled')) {
      store.remove(id)
      return
    }
    store.set(id, {
      scope,
      children,
      retry,
      retryLabel,
      hint,
      className,
      actionsClassName,
      priority,
      diagnostics,
      supportLink,
    })
  }, [
    store,
    scope,
    id,
    children,
    retry,
    retryLabel,
    hint,
    className,
    actionsClassName,
    priority,
    diagnostics,
    supportLink,
  ])
  useLayoutEffect(() => () => store?.remove(id), [store, id])
  return context ? null : <ErrorNoticeView {...props} />
}

export function ErrorNoticeView({
  children,
  retry,
  retryLabel = '重试',
  hint,
  className = '',
  actionsClassName = '',
}: NoticeContent) {
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
    <>
      <div
        className={`${noticeStyles['notice']} ${utilitiesStyles['error'] + ' ' + noticeStyles['slot-error']} ${className}`}
        role="alert"
      >
        <span>{children instanceof Error ? children.message : children}</span>
        {(canRetry || (diagnostics && supportLink)) && (
          <div className={`${noticeStyles['notice-actions']} ${actionsClassName}`}>
            {canRetry && (
              <button type="button" disabled={wait > 0} onClick={retry}>
                {wait ? `${wait} 秒后重试` : retryLabel}
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
      {hint && <p>{hint}</p>}
    </>
  )
}
