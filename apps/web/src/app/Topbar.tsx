import controlsStyles from '../styles/controls.module.css'
import styles from './Topbar.module.css'
import { Breadcrumbs } from '@web/app/Breadcrumbs'
import { ReportNotifications } from '@web/features/reports/components/ReportNotifications'
import { useTheme } from '@web/lib/theme'
import { Menu, Moon, Sun, Search } from 'lucide-react'
import type * as React from 'react'

export function Topbar({
  navTriggerRef,
  setCommands,
  expandedNav,
  setExpandedNav,
}: {
  navTriggerRef: React.RefObject<HTMLButtonElement | null>
  setCommands: React.Dispatch<React.SetStateAction<boolean>>
  expandedNav: boolean
  setExpandedNav: (expanded: boolean) => void
}) {
  const { effective, setTheme } = useTheme()
  return (
    <header className={styles['topbar']}>
      <div className={styles['topbar-title']}>
        <button
          ref={navTriggerRef}
          className={`${controlsStyles['icon-button']} ${styles['nav-toggle']}`}
          aria-label={expandedNav ? '收起导航' : '展开导航'}
          aria-expanded={expandedNav}
          aria-controls="sidebar-navigation"
          onClick={() => setExpandedNav(!expandedNav)}
        >
          <Menu size={19} />
        </button>
        <Breadcrumbs />
      </div>
      <div className={styles['topbar-actions']}>
        <button
          className={controlsStyles['icon-button']}
          aria-label={effective === 'light' ? '切换深色' : '切换浅色'}
          title={effective === 'light' ? '切换深色' : '切换浅色'}
          onClick={() => setTheme(effective === 'light' ? 'dark' : 'light')}
        >
          {effective === 'light' ? <Moon size={18} /> : <Sun size={18} />}
        </button>
        <ReportNotifications />
        <button
          className={`${controlsStyles['icon-button']} ${styles['desktop-search']}`}
          aria-label="查找页面与操作"
          onClick={() => setCommands(true)}
        >
          <Search size={18} />
        </button>
      </div>
    </header>
  )
}
