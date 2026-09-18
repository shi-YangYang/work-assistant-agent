import { DesktopConnect, useDesktopReturn } from './DesktopConnect'
import { VoiceprintsPage } from './Voiceprints'
import { AudioLines } from 'lucide-react'
import { ReportNotifications, ReportObligations } from './ReportObligations'
import { ModelUsagePage } from './ModelUsage'
import {
  useCallback,
  useEffect,
  useState,
  useRef,
  useLayoutEffect,
  useSyncExternalStore,
  useMemo,
} from 'react'
import { Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router'
import {
  BriefcaseBusiness,
  FileText,
  LayoutDashboard,
  MessageSquare,
  Search,
  Settings,
  Users,
  LogOut,
  Command,
  UserRound,
  Palette,
  CalendarClock,
  Cpu,
  ChartColumn,
  PanelLeftOpen,
  PanelLeftClose,
  Plus,
  List,
  LifeBuoy,
  ChevronRight,
} from 'lucide-react'
import type { Identity } from '@paa/api-contracts'
import { api, setCsrf, write, isCancelled } from './api'
import { Workspace } from './workspace'
import { BusyButton, ErrorNotice } from './ui'
import { CommandPalette, type WebCommand } from './CommandPalette'
import { SessionDrafts, identityScope } from './session-drafts'
import { SupportPage } from './Support'
import { ConnectionNotice } from './connection'
import { useMobileViewport } from './mobile-viewport'
import { ModelServices } from './ModelServices'
import { DingTalkLogin, DingTalkResult, LoginMethods } from './DingTalk'
import { LoginBackground } from './LoginBackground'
import { SourcePage } from './Assistant'
import { Assistant } from './Conversations'
import { Breadcrumbs } from './Breadcrumbs'
import { WorkPage, WorkDetail, ReportsPage, ReportDetail } from './Records'
import {
  AccountPage,
  AppearancePage,
  MembersPage,
  RulesPage,
  TeamPage,
  TeamMetricPage,
  TeamMemberPage,
} from './Settings'

const pages = [
  {
    path: '/assistant',
    title: '工作助手',
    detail: '继续对话，记录进展与查询资料',
    icon: MessageSquare,
  },
  {
    path: '/work',
    title: '我的工作',
    detail: '查找工作事项，更新进展与下一步',
    icon: BriefcaseBusiness,
  },
  { path: '/reports', title: '我的报告', detail: '查看、编辑和提交日报与周报', icon: FileText },
  {
    path: '/team',
    title: '团队看板',
    detail: '了解员工进展、阻碍与汇报情况',
    icon: LayoutDashboard,
    admin: true,
  },
  {
    path: '/members',
    title: '成员管理',
    detail: '管理员工账号与访问权限',
    icon: Users,
    admin: true,
  },
]
const settingsPages = [
  {
    path: '/settings/voiceprints',
    title: '公司声纹',
    detail: '登记成员声音，供桌面会议识别发言者',
    icon: AudioLines,
    admin: true,
  },
  {
    path: '/settings/support',
    title: '问题反馈',
    detail: '描述使用问题，查看管理员处理结果',
    icon: LifeBuoy,
  },
  { path: '/settings/account', title: '账户', detail: '查看账号信息与修改密码', icon: UserRound },
  {
    path: '/settings/appearance',
    title: '外观',
    detail: '浅色、深色或跟随系统主题',
    icon: Palette,
  },
  {
    path: '/settings/rules',
    title: '汇报规则',
    detail: '查看汇报周期、时区与生成时间',
    icon: CalendarClock,
  },
  {
    path: '/settings/login',
    title: '登录方式',
    detail: '配置钉钉登录与授权',
    icon: UserRound,
    admin: true,
  },
  {
    path: '/settings/models',
    title: '模型服务管理',
    detail: '配置模型 API、服务连接与用途',
    icon: Cpu,
    admin: true,
  },
  {
    path: '/settings/usage',
    title: '模型用量',
    detail: '查看调用状态、耗时与 Token 用量',
    icon: ChartColumn,
    admin: true,
  },
]
export function App() {
  const [vault] = useState(() => new SessionDrafts())
  const [identity, setIdentity] = useState<Identity | null>(null)
  const [loading, setLoading] = useState(true)
  const location = useLocation()
  const navigate = useNavigate()
  useDesktopReturn(identity)
  const verified = useRef<string | null>(null)
  const [loadError, setLoadError] = useState<Error | string>('')
  useEffect(() => {
    const controller = new AbortController()
    void api<Identity>('/auth/me', { signal: controller.signal })
      .then((value) => {
        if (controller.signal.aborted) return
        setCsrf(value.csrf)
        vault.resume(value)
        verified.current = identityScope(value)
        setIdentity(value)
      })
      .catch((e) => {
        if (!controller.signal.aborted && !isCancelled(e) && e.status !== 401) setLoadError(e)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    const expire = () => {
      vault.suspend()
      if (verified.current) setLoadError('登录已过期，请重新登录。聊天草稿仅在原账号验证后恢复。')
      setIdentity(null)
    }
    const forbidden = () => vault.clear()
    window.addEventListener('paa-session-expired', expire)
    window.addEventListener('paa-access-forbidden', forbidden)
    return () => {
      controller.abort()
      window.removeEventListener('paa-session-expired', expire)
      window.removeEventListener('paa-access-forbidden', forbidden)
    }
  }, [vault])
  const logout = () => {
    verified.current = null
    vault.clear()
    setCsrf('')
    setLoadError('')
    setIdentity(null)
    if (location.pathname !== '/desktop/connect') void navigate('/', { replace: true })
  }
  if (loading)
    return (
      <div className="login">
        <p>正在连接…</p>
      </div>
    )
  if (!identity)
    return (
      <Login
        vault={vault}
        initialError={loadError}
        onLogin={async (value) => {
          const changedAccount = verified.current && verified.current !== identityScope(value)
          setCsrf(value.csrf)
          vault.resume(value)
          if (changedAccount && location.pathname !== '/desktop/connect')
            await navigate('/', { replace: true })
          verified.current = identityScope(value)
          setLoadError('')
          setIdentity(value)
        }}
      />
    )
  if (identity.member.mustChangePassword)
    return (
      <div className="login">
        <div className="login-card">
          <h1>设置你的密码</h1>
          <p>首次登录，请更换管理员提供的临时密码。</p>
          <AccountPage force member={identity.member} onLogout={logout} />
        </div>
      </div>
    )
  if (location.pathname === '/desktop/connect')
    return <DesktopConnect identity={identity} onLogout={logout} />
  return <Shell key={identityScope(identity)} identity={identity} vault={vault} onLogout={logout} />
}
function Login({
  vault,
  onLogin,
  initialError,
}: {
  vault: SessionDrafts
  onLogin: (value: Identity) => void | Promise<void>
  initialError: Error | string
}) {
  const [error, setError] = useState(initialError)
  const [busy, setBusy] = useState(false)
  return (
    <main className="login login-page">
      <LoginBackground />
      <section className="login-panel" aria-labelledby="login-title">
        <header className="login-heading">
          <span className="brand-mark" aria-hidden="true" />
          <h1 id="login-title">登录工作助手</h1>
        </header>
        <DingTalkResult />
        <DingTalkLogin vault={vault} />
        <form
          className="login-form"
          onSubmit={async (e) => {
            e.preventDefault()
            const data = new FormData(e.currentTarget)
            setBusy(true)
            try {
              await onLogin(
                await write<Identity>('/auth/login', {
                  username: data.get('username'),
                  password: data.get('password'),
                }),
              )
            } catch (e) {
              setError(e as Error)
            } finally {
              setBusy(false)
            }
          }}
        >
          <label>
            账号
            <input
              name="username"
              placeholder="输入账号"
              autoComplete="username"
              required
              maxLength={80}
            />
          </label>
          <label>
            密码
            <input
              name="password"
              type="password"
              placeholder="输入密码"
              autoComplete="current-password"
              required
              maxLength={128}
            />
          </label>
          <ErrorNotice>{error}</ErrorNotice>
          <BusyButton busy={busy} className="primary">
            登录
          </BusyButton>
        </form>
        <small className="login-help">尚无账号？请联系公司管理员</small>
      </section>
    </main>
  )
}
function Shell({
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
      await write('/auth/logout', {})
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
        <aside
          className="sidebar"
          onKeyDown={(event) => {
            if (event.key === 'Escape') setExpandedNav(false)
          }}
        >
          <button
            className="icon-button sidebar-toggle"
            aria-label={expandedNav ? '收起导航' : '展开导航'}
            aria-expanded={expandedNav}
            onClick={() => setExpandedNav(!expandedNav)}
          >
            {expandedNav ? <PanelLeftClose size={19} /> : <PanelLeftOpen size={19} />}
          </button>
          <Link to={identity.member.role === 'admin' ? '/team' : '/assistant'} className="brand">
            <span className="brand-mark" aria-hidden="true" />
            <span className="nav-label">公司工作助手</span>
          </Link>
          <button
            className="search-launch"
            title="查找页面与操作"
            aria-label="查找页面与操作"
            onClick={() => setCommands(true)}
          >
            <Command size={16} /> <span className="nav-label">查找页面与操作</span>
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
                <span className="nav-label">{p.title}</span>
              </NavLink>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <button
              ref={settingsTrigger}
              className={`settings-toggle ${location.pathname.startsWith('/settings/') ? 'active' : ''}`}
              aria-expanded={settingsOpen}
              aria-controls="sidebar-settings"
              title="系统设置"
              popoverTarget="sidebar-settings"
            >
              <Settings size={18} />
              <span className="nav-label">系统设置</span>
              <ChevronRight size={15} className="settings-chevron nav-label" />
            </button>
            <div
              ref={settingsPanel}
              id="sidebar-settings"
              className="settings-popover"
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
                        ? 'settings-section-start'
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
            <div className="identity">
              <span className="avatar">{accountName.slice(0, 1)}</span>
              <span className="nav-label">
                {accountName}
                {identity.member.role !== 'admin' && <small>用户</small>}
              </span>
              <button className="icon-button" aria-label="退出登录" onClick={logout}>
                <LogOut size={17} />
              </button>
            </div>
          </div>
        </aside>
        <section className="main">
          <header className="topbar">
            <div className="topbar-title">
              <Breadcrumbs />
            </div>
            <div className="topbar-actions">
              <ReportNotifications />
              <div className="mobile-tools">
                <button
                  className="icon-button"
                  aria-label="查找页面与操作"
                  onClick={() => setCommands(true)}
                >
                  <Search size={19} />
                </button>
                <Link className="icon-button" aria-label="设置" to="/settings/account">
                  <Settings size={19} />
                </Link>
              </div>
            </div>
          </header>
          <ConnectionNotice />
          {!['/settings/account', '/settings/login'].includes(location.pathname) && (
            <DingTalkResult />
          )}
          <Routes>
            <Route
              path="/"
              element={
                <Navigate to={identity.member.role === 'admin' ? '/team' : '/assistant'} replace />
              }
            />
            <Route path="/assistant" element={<Assistant />} />
            <Route path="/assistant/:conversationId" element={<Assistant />} />
            <Route path="/messages/:id" element={<SourcePage />} />
            <Route path="/work" element={<WorkPage />} />
            <Route path="/work/:id" element={<WorkDetail />} />
            <Route
              path="/reports"
              element={
                identity.member.role === 'employee' ? (
                  <ReportsPage />
                ) : (
                  <Navigate to="/team" replace />
                )
              }
            />
            <Route path="/reports/:id" element={<ReportDetail />} />
            {identity.member.role === 'admin' && (
              <>
                <Route path="/team" element={<TeamPage />} />
                <Route path="/team/details" element={<TeamMetricPage />} />
                <Route path="/team/reports" element={<ReportObligations team />} />
                <Route path="/team/:id" element={<TeamMemberPage />} />
                <Route path="/members" element={<MembersPage />} />
              </>
            )}
            <Route
              path="/settings/*"
              element={
                <div className="settings-layout">
                  <nav className="settings-nav" aria-label="设置页面">
                    {allowedSettings.map((p) => (
                      <NavLink
                        key={p.path}
                        to={p.path}
                        title={p.title}
                        aria-label={p.title}
                        onClick={() => setExpandedNav(false)}
                      >
                        {p.title}
                      </NavLink>
                    ))}
                  </nav>
                  <Routes>
                    <Route
                      path="account"
                      element={<AccountPage member={identity.member} onLogout={onLogout} />}
                    />
                    <Route path="support" element={<SupportPage />} />
                    <Route path="appearance" element={<AppearancePage />} />
                    <Route path="rules" element={<RulesPage />} />
                    {identity.member.role === 'admin' && (
                      <>
                        <Route path="models" element={<ModelServices />} />
                        <Route path="voiceprints" element={<VoiceprintsPage />} />
                        <Route path="login" element={<LoginMethods />} />
                        <Route path="usage" element={<ModelUsagePage />} />
                      </>
                    )}
                    <Route path="*" element={<Navigate to="/settings/account" replace />} />
                  </Routes>
                </div>
              }
            />
            <Route path="*" element={<Navigate to="/assistant" replace />} />
          </Routes>
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
  )
}
