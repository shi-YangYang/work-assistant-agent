import type { Identity } from '@paa/api-contracts'
import { AppRoutes } from '@web/app/AppRoutes'
import { pages, settingsPages } from '@web/app/navigation-items'
import { Sidebar } from '@web/app/Sidebar'
import { Topbar } from '@web/app/Topbar'
import type { WebCommand } from '@web/components/CommandPalette'
import { CommandPalette } from '@web/components/CommandPalette'
import { ConnectionNotice } from '@web/components/ConnectionNotice'
import { logout as requestLogout } from '@web/features/auth/api/requests'
import { DingTalkResult } from '@web/features/auth/components/DingTalkResult'
import { useMobileViewport } from '@web/hooks/useMobileViewport'
import { SessionDrafts } from '@web/lib/session-drafts'
import { SupportLink } from '@web/lib/support-link'
import { Workspace } from '@web/lib/workspace'
import { List, Plus } from 'lucide-react'
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router'

export function Shell({
  identity,
  onLogout,
  vault,
}: {
  identity: Identity
  onLogout: () => void
  vault: SessionDrafts
}) {
  useMobileViewport()
  const accountName = identity.member.role === 'admin' ? '管理员' : identity.member.name
  const drafts = useSyncExternalStore(vault.subscribe, vault.getSnapshot)
  const writerGeneration = vault.version
  const setDraft = useMemo(() => vault.writer(writerGeneration), [vault, writerGeneration])
  const [toast, setToast] = useState('')
  const [commands, setCommands] = useState(false)
  const conversationStorageKey = `paa.company.last-conversation:${identity.company.id}:${identity.member.id}`
  const [lastConversationId, setLastConversationId] = useState<string | null>(() => {
    try {
      return sessionStorage.getItem(conversationStorageKey)
    } catch {
      return null
    }
  })
  const rememberConversation = useCallback(
    (id: string | null) => {
      setLastConversationId(id)
      try {
        if (id) sessionStorage.setItem(conversationStorageKey, id)
        else sessionStorage.removeItem(conversationStorageKey)
      } catch {
        /* In-memory navigation still works when storage is unavailable. */
      }
    },
    [conversationStorageKey],
  )
  const [expandedNav, setExpandedNav] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  const scrollPositions = useRef(new Map<string, number>())
  useLayoutEffect(() => {
    const key = location.pathname + location.search
    const node = document.querySelector<HTMLElement>('.page, .settings-layout')
    if (node) node.scrollTop = scrollPositions.current.get(key) ?? 0
    const positions = scrollPositions.current
    return () => {
      if (node) positions.set(key, node.scrollTop)
    }
  }, [location.pathname, location.search])

  const allowedSettings = settingsPages.filter((p) => !p.admin || identity.member.role === 'admin')
  const allowed = pages.filter(
    (p) =>
      (!p.admin || identity.member.role === 'admin') &&
      !(p.path === '/reports' && identity.member.role === 'admin'),
  )
  useEffect(() => {
    if (!toast) return
    const id = setTimeout(() => setToast(''), 4000)
    return () => clearTimeout(id)
  }, [toast])
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.isComposing) return
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setCommands(true)
      }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [])
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (Object.keys(drafts).length) {
        e.preventDefault()
        e.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [drafts])
  const logout = async () => {
    if (Object.keys(drafts).length && !window.confirm('还有尚未保存的内容，确定退出登录？')) return
    try {
      await requestLogout({})
      onLogout()
    } catch (e) {
      setToast((e as Error).message)
    }
  }
  const openCommandPage = (path: string) => {
    if (drafts.recording) {
      setToast('请先停止录音，再切换页面；已录制的内容会保留。')
      return
    }
    setExpandedNav(false)
    navigate(path)
  }
  const commandItems: WebCommand[] = [
    {
      id: 'new-conversation',
      label: '新会话',
      detail: '从一个新的话题开始',
      group: '快捷操作',
      icon: Plus,
      run: () => openCommandPage('/assistant?new=1'),
    },
    {
      id: 'find-conversation',
      label: '查找会话',
      detail: '搜索、切换和管理已有会话',
      group: '快捷操作',
      icon: List,
      run: () => openCommandPage('/assistant?conversations=1'),
    },
    ...allowed.map((page) => ({
      id: page.path,
      label: page.title,
      detail: page.detail,
      group: '工作空间',
      icon: page.icon,
      current: location.pathname === page.path || location.pathname.startsWith(page.path + '/'),
      run: () => openCommandPage(page.path),
    })),
    ...allowedSettings.map((page) => ({
      id: page.path,
      label: page.title,
      detail: page.detail,
      group: '设置',
      icon: page.icon,
      current: location.pathname === page.path,
      run: () => openCommandPage(page.path),
    })),
  ]
  return (
    <SupportLink.Provider value="/settings/support">
      <Workspace.Provider
        value={{
          identity,
          drafts,
          setDraft,
          notify: setToast,
          lastConversationId,
          rememberConversation,
        }}
      >
        <div
          className={`company-shell ${expandedNav ? 'nav-expanded' : ''}`}
          onClickCapture={(event) => {
            if (
              drafts.recording &&
              (event.target as HTMLElement).closest('a[href]') &&
              !window.confirm('离开工作助手会停止录音，并保留已录制内容供你试听或发送。继续？')
            ) {
              event.preventDefault()
              event.stopPropagation()
            }
          }}
        >
          {expandedNav && (
            <button
              className="nav-backdrop"
              aria-label="收起导航"
              onClick={() => setExpandedNav(false)}
            />
          )}
          <Sidebar
            setExpandedNav={setExpandedNav}
            expandedNav={expandedNav}
            identity={identity}
            setCommands={setCommands}
            allowed={allowed}
            location={location}
            allowedSettings={allowedSettings}
            accountName={accountName}
            logout={logout}
          />
          <section className="main">
            <Topbar setCommands={setCommands} />
            <ConnectionNotice />
            {!['/settings/account', '/settings/login'].includes(location.pathname) && (
              <DingTalkResult />
            )}
            <AppRoutes
              identity={identity}
              allowedSettings={allowedSettings}
              setExpandedNav={setExpandedNav}
              onLogout={onLogout}
            />
            <nav className="mobile-nav">
              {allowed
                .filter((p) => p.path !== '/members')
                .map((p) => (
                  <NavLink
                    key={p.path}
                    to={p.path}
                    title={p.title}
                    aria-label={p.title}
                    onClick={() => setExpandedNav(false)}
                  >
                    <p.icon size={19} />
                    <span>{p.title}</span>
                  </NavLink>
                ))}
            </nav>
          </section>
        </div>
        {toast && (
          <div className="toast" role="status">
            {toast}
          </div>
        )}
        {commands && <CommandPalette commands={commandItems} onClose={() => setCommands(false)} />}
      </Workspace.Provider>
    </SupportLink.Provider>
  )
}
