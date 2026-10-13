import { NotificationsView } from '@web/features/notifications/components/NotificationsView'
import { AnnouncementsList } from '@web/features/announcements/components/AnnouncementsList'
import { ReportNotifications } from '@web/features/reports/components/notifications/ReportNotifications'

export function NotificationsPage() {
  return (
    <NotificationsView
      reminders={(active) => <ReportNotifications active={active} />}
      announcements={(active) => <AnnouncementsList active={active} />}
    />
  )
}
