import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { epoch } from '@web/api/client'
import { QueryResource, sharedResource } from '@web/lib/query-resource'
import { useQueryResource } from '@web/hooks/useQueryResource'
import { NotificationContext } from '../hooks/useNotificationSummary'
import { readNotificationSummary } from '../api/requests'

export function NotificationProvider({ children, scope }: { children: ReactNode; scope: string }) {
  const [lastTab, selectTab] = useState<'reminders' | 'announcements' | null>(null)
  const generation = epoch
  const resource = useMemo(
    () =>
      sharedResource(
        `notification-summary:${generation}:${scope}`,
        (evict) => new QueryResource(readNotificationSummary, evict),
      ),
    [scope, generation],
  )
  const snapshot = useQueryResource(resource)
  useEffect(() => {
    const refresh = () => {
      if (!document.hidden) void resource.refresh()
    }
    const invalidate = () => {
      void resource.invalidate()
    }
    const timer = setInterval(refresh, 30000)
    window.addEventListener('focus', refresh)
    window.addEventListener('online', refresh)
    window.addEventListener('paa-notifications-changed', invalidate)
    document.addEventListener('visibilitychange', refresh)
    return () => {
      clearInterval(timer)
      window.removeEventListener('focus', refresh)
      window.removeEventListener('online', refresh)
      window.removeEventListener('paa-notifications-changed', invalidate)
      document.removeEventListener('visibilitychange', refresh)
      // QueryResource releases inactive resources after its normal grace period.
    }
  }, [resource])
  return (
    <NotificationContext.Provider
      value={{ ...snapshot, refresh: resource.refresh, lastTab, selectTab }}
    >
      {children}
    </NotificationContext.Provider>
  )
}
