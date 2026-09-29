import type { ContextType, ReactNode } from 'react'
import { useContext, useId, useLayoutEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { ApiError } from '@web/api/client'
import { useConnectionMessage } from '@web/hooks/useConnectionMessage'
import { createNoticeStore, ErrorNoticeContext } from '@web/lib/error-notices'
import { ErrorDiagnostics, SupportLink } from '@web/lib/support-link'
import { ErrorNoticeView } from './ErrorNotice'
import styles from './ErrorNoticeScope.module.css'

// Scopes share one store: a dialog takes precedence over the assistant and page outlets.
export function ErrorNoticeScope({
  children,
  priority = 0,
  isolate = false,
}: {
  children: ReactNode
  priority?: number
  isolate?: boolean
}) {
  const parent = useContext(ErrorNoticeContext)
  const scope = useId()
  const [store] = useState(() => parent?.store ?? createNoticeStore())
  const connection = useConnectionMessage(!parent)
  const connectionMessage = parent?.connectionMessage ?? connection
  const level = (parent?.priority ?? 0) + priority
  const ancestors = parent?.visibleScopes
  useLayoutEffect(() => store.enter(scope, level), [store, scope, level])
  const context = useMemo(
    () => ({
      store,
      scope,
      priority: level,
      connectionMessage,
      visibleScopes: [scope, ...(isolate ? [] : (ancestors ?? []))],
    }),
    [store, scope, level, connectionMessage, isolate, ancestors],
  )
  return <ErrorNoticeContext.Provider value={context}>{children}</ErrorNoticeContext.Provider>
}

export function ErrorNoticeOutlet({
  label = '页面提示',
  className = '',
}: {
  label?: string
  className?: string
}) {
  const context = useContext(ErrorNoticeContext)
  if (!context) return null
  return <NoticeOutlet context={context} label={label} className={className} />
}

function NoticeOutlet({
  context,
  label,
  className,
}: {
  context: NonNullable<ContextType<typeof ErrorNoticeContext>>
  label: string
  className: string
}) {
  const { store, scope, connectionMessage } = context
  const snapshot = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot)
  const diagnostics = useContext(ErrorDiagnostics)
  const supportLink = useContext(SupportLink)
  if (snapshot.activeScope !== scope) return null
  const notices = snapshot.notices.filter((notice) => context.visibleScopes.includes(notice.scope))
  const primary = notices
    .slice()
    .reverse()
    .sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0))[0]
  if (!primary && !connectionMessage) return null
  const message = (value: unknown) => (value instanceof Error ? value.message : value)
  const matching = primary
    ? notices.filter((notice) => message(notice.children) === message(primary.children))
    : []
  const retryable = matching.filter(
    (notice) =>
      notice.retry && (!(notice.children instanceof ApiError) || notice.children.retryable),
  )
  const retries = [...new Set(retryable.map((notice) => notice.retry!))]
  // Identical failures may belong to several independent reads; retry each read once.
  const retry = retries.length ? () => retries.forEach((run) => run()) : undefined
  const cooldown = retryable.reduce<Error | undefined>((latest, notice) => {
    const error = notice.children
    return error instanceof ApiError &&
      error.retryAt > (latest instanceof ApiError ? latest.retryAt : 0)
      ? error
      : latest
  }, undefined)
  return (
    <section
      className={`${styles['error-outlet']} ${className}`}
      data-placed={className ? true : undefined}
      aria-label={label}
    >
      <ErrorDiagnostics.Provider value={primary?.diagnostics ?? diagnostics}>
        <SupportLink.Provider value={primary?.supportLink ?? supportLink}>
          <ErrorNoticeView {...primary} retry={retry}>
            {cooldown ?? primary?.children ?? connectionMessage}
          </ErrorNoticeView>
        </SupportLink.Provider>
      </ErrorDiagnostics.Provider>
    </section>
  )
}
