import type { NotificationSummary } from '@paa/api-contracts'
import { api } from '@web/api/client'

export function readNotificationSummary(signal: AbortSignal) {
  return api<NotificationSummary>('/notification-summary', { signal })
}
