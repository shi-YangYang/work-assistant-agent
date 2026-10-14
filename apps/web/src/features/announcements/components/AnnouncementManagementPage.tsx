import { Link, useLocation } from 'react-router'
import { PageHeader } from '@web/components/layout/page-header/PageHeader'
import { AnnouncementsList } from './AnnouncementsList'
import styles from './Announcements.module.css'

export function AnnouncementManagementPage() {
  const location = useLocation()
  return (
    <div className={styles.page} data-scroll-container>
      <PageHeader
        title="公告管理"
        actions={
          <Link
            className={styles.publish}
            to="/announcement-management/new"
            state={{ returnTo: location.pathname + location.search }}
          >
            发布公告
          </Link>
        }
      />
      <AnnouncementsList management />
    </div>
  )
}
