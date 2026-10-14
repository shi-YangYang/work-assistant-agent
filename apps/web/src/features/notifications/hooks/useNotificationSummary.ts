import { createContext, useContext } from 'react'
import type { NotificationSummary } from '@paa/api-contracts'

export const NotificationContext = createContext<{
  data: NotificationSummary | null
  error: Error | string
  refresh: () => Promise<void>
  lastTab: 'reminders' | 'announcements' | null
  selectTab: (tab: 'reminders' | 'announcements') => void
} | null>(null)
export function useNotificationSummary() {
  return useContext(NotificationContext)
}
// Writes can invalidate the one shell-owned subscription without coupling
// announcements or reports to another business feature.
