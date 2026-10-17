import controlsStyles from '../../styles/controls.module.css'
import layoutStyles from '../../styles/layout.module.css'
import styles from './Sidebar.module.css'
import type { Identity } from '@paa/api-contracts'
import type { LucideIcon } from 'lucide-react'
import {
  ArrowLeft,
  Bell,
  ChevronRight,
  Cloud,
  Eye,
  EyeOff,
  Search,
  LogOut,
  Settings,
} from 'lucide-react'
import type * as React from 'react'
import { identityScope } from '@web/lib/session-drafts'
import { useSidebarNavigation } from './useSidebarNavigation'
import type { Location } from 'react-router'
import { Link, NavLink } from 'react-router'
import { useNotificationSummary } from '@web/features/notifications/hooks/useNotificationSummary'

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
  petVisible,
  setPetVisible,
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
  petVisible: boolean
  setPetVisible: (visible: boolean) => void
}) {
  const unread = useNotificationSummary()?.data?.totalUnread ?? 0
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
      <div className={styles['sidebar-header']}>
        <Link to="/assistant" className={styles['brand']} aria-label="Noria 首页">
          Noria
        </Link>
        <div className={styles['header-actions']}>
          {!petVisible && (
            <Link
              to="/notifications"
              className={styles['notification-launch']}
              aria-label={unread > 0 ? `通知，${unread} 条未读` : '通知'}
              title={unread > 0 ? `通知，${unread} 条未读` : '通知'}
              onClick={() => setExpandedNav(false)}
            >
              <Bell size={20} aria-hidden="true" />
              {unread > 0 && (
                <span className={styles['notification-count']} aria-hidden="true">
                  {unread > 99 ? '99+' : unread}
                </span>
              )}
            </Link>
          )}
          <button
            type="button"
            className={styles['search-launch']}
            title={`查找页面与操作（${navigator.platform.includes('Mac') ? '⌘ K' : 'Ctrl K'}）`}
            aria-label="查找页面与操作"
            onClick={() => setCommands(true)}
          >
            <Search size={20} aria-hidden="true" />
          </button>
        </div>
      </div>
      <nav aria-label={settingsMenu ? '系统设置' : '工作空间'}>
        {settingsMenu && <span className={styles['navigation-label']}>系统设置</span>}
        {entries.map((p) => (
          <NavLink
            key={p.path}
            to={p.path}
            title={p.title}
            aria-label={p.title}
            onClick={() => setExpandedNav(false)}
          >
            <p.icon size={18} />
            <span>{p.title}</span>
          </NavLink>
        ))}
        {settingsMenu && (
          <button
            type="button"
            className={styles['settings-action']}
            onClick={() => setPetVisible(!petVisible)}
          >
            {petVisible ? (
              <EyeOff size={18} aria-hidden="true" />
            ) : (
              <Eye size={18} aria-hidden="true" />
            )}
            <span>{petVisible ? '隐藏宠物' : '显示宠物'}</span>
          </button>
        )}
        {!settingsMenu && (
          <button
            type="button"
            className={styles['disabled-entry']}
            disabled
            aria-label="云搭子 beta"
            title="云搭子 beta · 即将开放"
          >
            <Cloud size={18} aria-hidden="true" />
            <span>云搭子</span>
            <span className={styles['beta-badge']}>beta</span>
          </button>
        )}
      </nav>
      <div className={styles['sidebar-bottom']}>
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
            <span>返回主菜单</span>
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
            <span>系统设置</span>
            <ChevronRight size={15} className={styles['settings-chevron']} />
          </button>
        )}
        <div className={styles['identity']}>
          <span className={layoutStyles['avatar']}>{accountName.slice(0, 1)}</span>
          <span>
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
