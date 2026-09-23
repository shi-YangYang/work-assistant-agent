import controlsStyles from '../styles/controls.module.css'
import layoutStyles from '../styles/layout.module.css'
import styles from './Sidebar.module.css'
import type { Identity } from '@paa/api-contracts'
import type { LucideIcon } from 'lucide-react'
import {
  ChevronRight,
  Command,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
} from 'lucide-react'
import type * as React from 'react'
import { useLayoutEffect, useRef, useState } from 'react'
import type { Location } from 'react-router'
import { Link, NavLink } from 'react-router'

export function Sidebar({
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
  setExpandedNav: React.Dispatch<React.SetStateAction<boolean>>
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
  const [settingsOpen, setSettingsOpen] = useState(false)
  const settingsTrigger = useRef<HTMLButtonElement>(null)
  const settingsPanel = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    if (!settingsOpen) return
    const position = () => {
      const panel = settingsPanel.current
      const trigger = settingsTrigger.current
      if (!panel || !trigger) return
      if (window.innerWidth <= 760) {
        panel.hidePopover()
        return
      }
      const rect = trigger.getBoundingClientRect()
      panel.style.left = `${Math.min(rect.right + 10, window.innerWidth - panel.offsetWidth - 12)}px`
      panel.style.top = `${Math.max(12, Math.min(rect.bottom - panel.offsetHeight, window.innerHeight - panel.offsetHeight - 12))}px`
    }
    position()
    window.addEventListener('resize', position)
    window.addEventListener('scroll', position, true)
    return () => {
      window.removeEventListener('resize', position)
      window.removeEventListener('scroll', position, true)
    }
  }, [settingsOpen])
  return (
    <aside
      className={styles['sidebar']}
      data-expanded={expandedNav}
      onKeyDown={(event) => {
        if (event.key === 'Escape') setExpandedNav(false)
      }}
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
      >
        <span className={'brand-mark'} aria-hidden="true" />
        <span className={styles['nav-label']}>公司工作助手</span>
      </Link>
      <button
        className={styles['search-launch']}
        title="查找页面与操作"
        aria-label="查找页面与操作"
        onClick={() => setCommands(true)}
      >
        <Command size={16} /> <span className={styles['nav-label']}>查找页面与操作</span>
        <kbd>{navigator.platform.includes('Mac') ? '⌘ K' : 'Ctrl K'}</kbd>
      </button>
      <nav aria-label="工作空间">
        {allowed.map((p) => (
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
      </nav>
      <div className={styles['sidebar-bottom']}>
        <button
          ref={settingsTrigger}
          className={styles['settings-toggle']}
          data-active={location.pathname.startsWith('/settings/')}
          aria-expanded={settingsOpen}
          aria-controls="sidebar-settings"
          title="系统设置"
          popoverTarget="sidebar-settings"
        >
          <Settings size={18} />
          <span className={styles['nav-label']}>系统设置</span>
          <ChevronRight
            size={15}
            className={`${styles['settings-chevron']} ${styles['nav-label']}`}
          />
        </button>
        <div
          ref={settingsPanel}
          id="sidebar-settings"
          className={styles['settings-popover']}
          popover="auto"
          onToggle={(event) => setSettingsOpen(event.newState === 'open')}
        >
          <nav aria-label="系统设置">
            {[
              ...allowedSettings.filter((p) => p.path !== '/settings/support'),
              ...allowedSettings.filter((p) => p.path === '/settings/support'),
            ].map((p) => (
              <NavLink
                key={p.path}
                to={p.path}
                className={
                  p.path === '/settings/rules' || p.path === '/settings/support'
                    ? styles['settings-section-start']
                    : undefined
                }
                title={p.title}
                aria-label={p.title}
                onClick={() => {
                  settingsPanel.current?.hidePopover()
                  setExpandedNav(false)
                }}
              >
                <p.icon size={16} />
                <span>{p.title}</span>
              </NavLink>
            ))}
          </nav>
        </div>
        <div className={styles['identity']}>
          <span className={`${layoutStyles['avatar']} ${styles['slot-avatar']}`}>
            {accountName.slice(0, 1)}
          </span>
          <span className={styles['nav-label']}>
            {accountName}
            {identity.member.role !== 'admin' && <small>用户</small>}
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
