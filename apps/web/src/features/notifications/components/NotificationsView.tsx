import { useEffect, type ReactNode } from 'react'
import { useSearchParams } from 'react-router'
import { PageHeader } from '@web/components/layout/page-header/PageHeader'
import { ErrorNoticeView as ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { useNotificationSummary } from '@web/features/notifications/hooks/useNotificationSummary'
import { useWorkspace } from '@web/lib/workspace'
import layout from '@web/styles/layout.module.css'
import styles from '@web/features/notifications/components/NotificationsPage.module.css'

const tabs = [
  { id: 'reminders', label: '提醒' },
  { id: 'announcements', label: '公告' },
] as const
export function NotificationsView({
  reminders,
  announcements,
}: {
  reminders: (active: boolean) => ReactNode
  announcements: (active: boolean) => ReactNode
}) {
  const { identity } = useWorkspace()
  const summary = useNotificationSummary()
  const [params, setParams] = useSearchParams()
  const requested = params.get('tab')
  const tab =
    requested === 'reminders' || requested === 'announcements'
      ? requested
      : (summary?.lastTab ??
        (summary?.data?.remindersUnread
          ? 'reminders'
          : summary?.data?.announcementsUnread
            ? 'announcements'
            : identity.member.role === 'admin'
              ? 'announcements'
              : 'reminders'))
  const selectTab = summary?.selectTab
  const refresh = summary?.refresh
  useEffect(() => {
    void refresh?.()
  }, [refresh])
  useEffect(() => {
    if (!params.has('tab') && !summary?.data && !summary?.error) return
    selectTab?.(tab)
    if (requested !== tab) {
      const next = new URLSearchParams(params)
      next.set('tab', tab)
      setParams(next, { replace: true })
    }
  }, [tab, requested, params, setParams, selectTab, summary?.data, summary?.error])
  const choose = (nextTab: typeof tab) => {
    const next = new URLSearchParams(params)
    next.set('tab', nextTab)
    setParams(next)
  }
  return (
    <div className={styles.page} data-scroll-container>
      <PageHeader title="通知" />
      <div role="tablist" aria-label="通知分类" className={`${layout.tabs} ${styles.tabs}`}>
        {tabs.map((item, index) => {
          const unread =
            summary?.data?.[item.id === 'reminders' ? 'remindersUnread' : 'announcementsUnread'] ??
            0
          return (
            <button
              type="button"
              key={item.id}
              role="tab"
              id={`notification-tab-${item.id}`}
              aria-controls={`notification-panel-${item.id}`}
              aria-selected={tab === item.id}
              data-active={tab === item.id}
              tabIndex={tab === item.id ? 0 : -1}
              onClick={() => choose(item.id)}
              onKeyDown={(event) => {
                if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
                event.preventDefault()
                const next = event.key === 'Home' ? 0 : event.key === 'End' ? 1 : 1 - index
                choose(tabs[next].id)
                const buttons =
                  event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>(
                    '[role="tab"]',
                  )
                buttons?.[next]?.focus()
              }}
            >
              {item.label}
              {unread > 0 && <span className={styles.count}>{unread > 99 ? '99+' : unread}</span>}
            </button>
          )
        })}
      </div>
      <ErrorNotice retry={refresh}>{summary?.error}</ErrorNotice>
      <div
        role="tabpanel"
        id="notification-panel-reminders"
        aria-labelledby="notification-tab-reminders"
        hidden={tab !== 'reminders'}
      >
        {reminders(tab === 'reminders')}
      </div>
      <div
        role="tabpanel"
        id="notification-panel-announcements"
        aria-labelledby="notification-tab-announcements"
        hidden={tab !== 'announcements'}
      >
        {announcements(tab === 'announcements')}
      </div>
    </div>
  )
}
