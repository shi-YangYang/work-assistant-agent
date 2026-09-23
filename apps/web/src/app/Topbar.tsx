import controlsStyles from '../styles/controls.module.css'
import styles from './Topbar.module.css'
import { Breadcrumbs } from '@web/app/Breadcrumbs'
import { ReportNotifications } from '@web/features/reports/components/ReportNotifications'
import { Search, Settings } from 'lucide-react'
import type * as React from 'react'
import { Link } from 'react-router'

export function Topbar({
  setCommands,
}: {
  setCommands: React.Dispatch<React.SetStateAction<boolean>>
}) {
  return (
    <header className={styles['topbar']}>
      <div className={styles['topbar-title']}>
        <Breadcrumbs />
      </div>
      <div className={styles['topbar-actions']}>
        <ReportNotifications />
        <div className={styles['mobile-tools']}>
          <button
            className={`${controlsStyles['icon-button']} ${styles['slot-icon-button']}`}
            aria-label="查找页面与操作"
            onClick={() => setCommands(true)}
          >
            <Search size={19} />
          </button>
          <Link
            className={`${controlsStyles['icon-button']} ${styles['slot-icon-button']}`}
            aria-label="设置"
            to="/settings/account"
          >
            <Settings size={19} />
          </Link>
        </div>
      </div>
    </header>
  )
}
