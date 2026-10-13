import { NotificationEntry } from '@web/features/notifications/components/NotificationEntry'
import brandMark from '@paa/ui-web/mark.png'
import controlsStyles from '../../styles/controls.module.css'
import layoutStyles from '../../styles/layout.module.css'
import styles from './Sidebar.module.css'
import type { Identity } from '@paa/api-contracts'
import type { LucideIcon } from 'lucide-react'
import {
  ArrowLeft,
  ChevronRight,
  Cloud,
  Search,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
} from 'lucide-react'
import type * as React from 'react'
import { identityScope } from '@web/lib/session-drafts'
import { useSidebarNavigation } from './useSidebarNavigation'
import type { Location } from 'react-router'
import { Link, NavLink } from 'react-router'

export function Sidebar({
  sidebarRef,
  setExpandedNav,
  expandedNav,
  identity,
  setCommands,
  allowed,
  location,
  allowedSettings,
  accountName,
  logout,
}: {
  sidebarRef: React.RefObject<HTMLElement | null>
  setExpandedNav: (expanded: boolean) => void
  expandedNav: boolean
  identity: Identity
  setCommands: React.Dispatch<React.SetStateAction<boolean>>
  allowed: (
    | { path: string; title: string; detail: string; icon: LucideIcon; admin?: undefined }
    | { path: string; title: string; detail: string; icon: LucideIcon; admin: boolean }
  )[]
  location: Location<unknown>
  allowedSettings: (
    | { path: string; title: string; detail: string; icon: LucideIcon; admin: boolean }
    | { path: string; title: string; detail: string; icon: LucideIcon; admin?: undefined }
  )[]
  accountName: string
  logout: () => Promise<void>
}) {
  const { menu, selectMenu, settingsRef, backRef } = useSidebarNavigation(
    location,
    identityScope(identity),
  )
  const settingsMenu = menu === 'settings'
  const entries = settingsMenu
    ? [
        ...allowedSettings.filter((p) => p.path !== '/settings/support'),
        ...allowedSettings.filter((p) => p.path === '/settings/support'),
      ]
    : allowed
  return (
    <aside
      ref={sidebarRef}
      id="sidebar-navigation"
      className={styles['sidebar']}
      data-expanded={expandedNav}
      role={expandedNav ? 'dialog' : undefined}
      aria-modal={expandedNav || undefined}
      aria-label={expandedNav ? '导航' : undefined}
    >
      <button
        className={`${controlsStyles['icon-button']} ${styles['slot-icon-button']} ${styles['sidebar-toggle']}`}
        aria-label={expandedNav ? '收起导航' : '展开导航'}
        aria-expanded={expandedNav}
        onClick={() => setExpandedNav(!expandedNav)}
      >
        {expandedNav ? <PanelLeftClose size={19} /> : <PanelLeftOpen size={19} />}
      </button>
      <Link
        to={identity.member.role === 'admin' ? '/team' : '/assistant'}
        className={styles['brand']}
        aria-label="Noria 首页"
      >
        <img src={brandMark} className={styles['brand-mark']} alt="" aria-hidden="true" />
        <span className={styles['nav-label']}>
          Noria<small>你的AI伙伴</small>
        </span>
      </Link>
      <button
        className={styles['search-launch']}
        title="查找页面与操作"
        aria-label="查找页面与操作"
        onClick={() => setCommands(true)}
      >
        <Search size={17} /> <span className={styles['nav-label']}>查找页面与操作</span>
        <kbd>{navigator.platform.includes('Mac') ? '⌘ K' : 'Ctrl K'}</kbd>
      </button>
      <nav aria-label={settingsMenu ? '系统设置' : '工作空间'}>
        {settingsMenu && (
          <span className={`${styles['navigation-label']} ${styles['nav-label']}`}>系统设置</span>
        )}
        {entries.map((p) => (
          <NavLink
            key={p.path}
            to={p.path}
            title={p.title}
            aria-label={p.title}
            onClick={() => setExpandedNav(false)}
          >
            <p.icon size={18} />
            <span className={styles['nav-label']}>{p.title}</span>
          </NavLink>
        ))}
        {!settingsMenu && (
          <button
            type="button"
            className={styles['disabled-entry']}
            disabled
            aria-label="云搭子 beta"
            title="云搭子 beta · 即将开放"
          >
            <Cloud size={18} aria-hidden="true" />
            <span className={styles['nav-label']}>云搭子</span>
            <span className={`${styles['nav-label']} ${styles['beta-badge']}`}>beta</span>
          </button>
        )}
      </nav>
      <div className={styles['sidebar-bottom']}>
        <NotificationEntry
          className={styles['notification-entry']}
          labelClassName={styles['nav-label']}
          onNavigate={() => setExpandedNav(false)}
        />
        {settingsMenu ? (
          <button
            ref={backRef}
            type="button"
            className={styles['settings-toggle']}
            title="返回主菜单"
            aria-label="返回主菜单"
            onClick={() => selectMenu('main')}
          >
            <ArrowLeft size={18} aria-hidden="true" />
            <span className={styles['nav-label']}>返回主菜单</span>
          </button>
        ) : (
          <button
            ref={settingsRef}
            type="button"
            aria-label="系统设置"
            className={styles['settings-toggle']}
            data-active={location.pathname.startsWith('/settings/')}
            title="系统设置"
            onClick={() => {
              selectMenu('settings')
              setExpandedNav(true)
            }}
          >
            <Settings size={18} />
            <span className={styles['nav-label']}>系统设置</span>
            <ChevronRight
              size={15}
              className={`${styles['settings-chevron']} ${styles['nav-label']}`}
            />
          </button>
        )}
        <div className={styles['identity']}>
          <span className={`${layoutStyles['avatar']} ${styles['slot-avatar']}`}>
            {accountName.slice(0, 1)}
          </span>
          <span className={styles['nav-label']}>
            {accountName}
            <small>{identity.member.role === 'admin' ? '公司管理' : '个人工作空间'}</small>
          </span>
          <button
            className={`${controlsStyles['icon-button']} ${styles['slot-icon-button']}`}
            aria-label="退出登录"
            onClick={logout}
          >
            <LogOut size={17} />
          </button>
        </div>
      </div>
    </aside>
  )
}
