import { Bell } from 'lucide-react'
import { NavLink } from 'react-router'
import { useNotificationSummary } from '../hooks/useNotificationSummary'
import styles from './NotificationsPage.module.css'

export function NotificationEntry({
  className,
  labelClassName,
  onNavigate,
}: {
  className: string
  labelClassName: string
  onNavigate: () => void
}) {
  const unread = useNotificationSummary()?.data?.totalUnread ?? 0
  return (
    <NavLink
      to="/notifications"
      className={className}
      title="通知"
      aria-label={`通知${unread ? `，${unread} 条未读` : ''}`}
      onClick={onNavigate}
    >
      <Bell size={19} aria-hidden="true" />
      <span className={labelClassName}>通知</span>
      {unread > 0 && <span className={styles.count}>{unread > 99 ? '99+' : unread}</span>}
    </NavLink>
  )
}
