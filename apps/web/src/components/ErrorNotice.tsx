import { ApiError } from '@web/api/client'
import { useRetryWait } from '@web/hooks/useRetryWait'
import { captureDiagnostics, copyText, diagnosticText } from '@web/lib/diagnostics'
import { SupportLink } from '@web/lib/support-link'
import type { ReactNode } from 'react'
import { useContext, useMemo, useState } from 'react'
import { Link } from 'react-router'

export function ErrorNotice({
  children,
  retry,
}: {
  children: ReactNode | Error
  retry?: () => void
}) {
  const supportLink = useContext(SupportLink)
  const [copied, setCopied] = useState('')
  const wait = useRetryWait(children)
  const failure = children instanceof ApiError ? children : null
  const fallback = useMemo(
    () => (children instanceof ApiError ? children.diagnostics : captureDiagnostics()),
    [children],
  )
  if (!children || failure?.category === 'cancelled') return null
  const diagnostics = failure?.diagnostics ?? fallback
  return (
    <div className="notice error" role="alert">
      <span>{children instanceof Error ? children.message : children}</span>
      {failure?.requestId && <small className="request-id">请求编号：{failure.requestId}</small>}
      <div className="notice-actions">
        {retry && (!failure || failure.retryable) && (
          <button type="button" disabled={wait > 0} onClick={retry}>
            {wait ? `${wait} 秒后重试` : '重试'}
          </button>
        )}
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
      </div>
      {copied && <small role="status">{copied}</small>}
    </div>
  )
}
