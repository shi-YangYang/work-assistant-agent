import { useEffect, useState, useRef, useLayoutEffect } from 'react'
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
  ArrowLeft,
  AudioLines,
  ChevronRight,
  Command,
  UserRound,
  Palette,
  CalendarClock,
  Cpu,
  PanelLeftOpen,
  PanelLeftClose,
} from 'lucide-react'
import type { Identity } from '../shared/company-contracts'
import { api, setCsrf, write } from './api'
import { Workspace } from './workspace'
import { BusyButton, ErrorNotice, Modal } from './ui'
import type { DraftStore } from './workspace'
import { ModelServices } from './ModelServices'
import { detailContext, detailReturn, pageName } from './navigation'
import { Assistant, SourcePage } from './Assistant'
import { WorkPage, WorkDetail, ReportsPage, ReportDetail } from './Records'
import {
  AccountPage,
  AppearancePage,
  MembersPage,
  RulesPage,
  TeamPage,
  TeamMemberPage,
} from './Settings'

const pages = [
  { path: '/assistant', title: '工作助手', icon: MessageSquare },
  { path: '/work', title: '我的工作', icon: BriefcaseBusiness },
  { path: '/reports', title: '我的报告', icon: FileText },
  { path: '/team', title: '团队看板', icon: LayoutDashboard, admin: true },
  { path: '/members', title: '成员管理', icon: Users, admin: true },
]
const settingsPages = [
  { path: '/settings/account', title: '账户', icon: UserRound },
  { path: '/settings/appearance', title: '外观', icon: Palette },
  { path: '/settings/rules', title: '汇报规则', icon: CalendarClock },
  { path: '/settings/models', title: '模型服务管理', icon: Cpu, admin: true },
]
export function App() {
  const [identity, setIdentity] = useState<Identity | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    void api<Identity>('/auth/me', { signal: controller.signal })
      .then((value) => {
        setCsrf(value.csrf)
        setIdentity(value)
      })
      .catch((e) => {
        if (!controller.signal.aborted && e.status !== 401) setLoadError(e.message)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    const expire = () => {
      setCsrf('')
      setIdentity(null)
    }
    window.addEventListener('paa-session-expired', expire)
    return () => {
      controller.abort()
      window.removeEventListener('paa-session-expired', expire)
    }
  }, [])
  if (loading)
    return (
      <div className="login">
        <p>正在连接…</p>
      </div>
    )
  if (!identity)
    return (
      <Login
        initialError={loadError}
        onLogin={(value) => {
          setCsrf(value.csrf)
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
          <AccountPage force member={identity.member} onLogout={() => setIdentity(null)} />
        </div>
      </div>
    )
  return (
    <Shell
      key={identity.member.id}
      identity={identity}
      onLogout={() => {
        setCsrf('')
        setIdentity(null)
      }}
    />
  )
}
function Login({
  onLogin,
  initialError,
}: {
  onLogin: (value: Identity) => void
  initialError: string
}) {
  const [error, setError] = useState(initialError)
  const [busy, setBusy] = useState(false)
  return (
    <main className="login">
      <form
        className="login-card"
        onSubmit={async (e) => {
          e.preventDefault()
          const data = new FormData(e.currentTarget)
          setBusy(true)
          try {
            onLogin(
              await write<Identity>('/auth/login', {
                username: data.get('username'),
                password: data.get('password'),
              }),
            )
          } catch (e) {
            setError((e as Error).message)
          } finally {
            setBusy(false)
          }
        }}
      >
        <div className="brand">
          <span className="brand-mark">
            <AudioLines size={22} />
          </span>{' '}
          工作助手
        </div>
        <h1>欢迎回来</h1>
        <p>登录公司账号，继续记录和跟进工作。</p>
        <label>
          账号
          <input name="username" autoComplete="username" required maxLength={80} />
        </label>
        <label>
          密码
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            required
            maxLength={128}
          />
        </label>
        <ErrorNotice>{error}</ErrorNotice>
        <BusyButton busy={busy} className="primary">
          登录
        </BusyButton>
        <small>尚无账号？请联系公司的老板／管理员。</small>
      </form>
    </main>
  )
}
function Shell({ identity, onLogout }: { identity: Identity; onLogout: () => void }) {
  const [drafts, setDrafts] = useState<DraftStore>({})
  const [toast, setToast] = useState('')
  const [commands, setCommands] = useState(false)
  const [query, setQuery] = useState('')
  const [expandedNav, setExpandedNav] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  const latestDrafts = useRef(drafts)
  const scrollPositions = useRef(new Map<string, number>())
  useEffect(() => {
    latestDrafts.current = drafts
  }, [drafts])
  useEffect(
    () => () => {
      const composer = latestDrafts.current.composer as { files?: { url: string }[] } | undefined
      composer?.files?.forEach((file) => URL.revokeObjectURL(file.url))
    },
    [],
  )
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
  const allowed = pages.filter((p) => !p.admin || identity.member.role === 'admin')
  const setDraft = (key: string, value: unknown) =>
    setDrafts((previous) => {
      const next = { ...previous }
      const resolved = typeof value === 'function' ? value(previous[key]) : value
      if (resolved === undefined) delete next[key]
      else next[key] = resolved
      return next
    })
  useEffect(() => {
    if (!toast) return
    const id = setTimeout(() => setToast(''), 4000)
    return () => clearTimeout(id)
  }, [toast])
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (
        e.isComposing ||
        (e.target as HTMLElement).closest('input,textarea,[contenteditable=true]')
      )
        return
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
  const inSettings = location.pathname.startsWith('/settings/')
  const inDetail = !inSettings && location.pathname.split('/').length > 2
  const back = detailReturn(location.pathname, location.state)
  const current =
    [...allowed, ...allowedSettings].find((p) => location.pathname.startsWith(p.path))?.title ??
    pageName(location.pathname)
  return (
    <Workspace.Provider value={{ identity, drafts, setDraft, notify: setToast }}>
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
          <Link to="/assistant" className="brand">
            <span className="brand-mark">
              <AudioLines size={22} />
            </span>
            <span className="nav-label">{identity.company.name}</span>
          </Link>
          <button
            className="search-launch"
            title="查找页面"
            aria-label="查找页面"
            onClick={() => setCommands(true)}
          >
            <Command size={16} /> <span className="nav-label">查找页面</span>
            <kbd>{navigator.platform.includes('Mac') ? '⌘ K' : 'Ctrl K'}</kbd>
          </button>
          <p className="workspace-label">工作空间</p>
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
            <p className="workspace-label">设置</p>
            <nav aria-label="设置">
              {allowedSettings.map((p) => (
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
            <div className="identity">
              <span className="avatar">{identity.member.name.slice(0, 1)}</span>
              <span className="nav-label">
                {identity.member.name}
                <small>{identity.member.role === 'admin' ? '老板／管理员' : '员工'}</small>
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
              {inDetail && (
                <button
                  className="icon-button"
                  aria-label={`返回${back.label}`}
                  title={`返回${back.label}`}
                  onClick={() => navigate(back.path, { state: back.state })}
                >
                  <ArrowLeft size={18} />
                </button>
              )}
              <span className="breadcrumb-root">
                {inSettings ? '设置' : detailContext(location.state)}
              </span>
              <ChevronRight size={14} aria-hidden="true" />
              <strong>{inDetail ? pageName(location.pathname) : current}</strong>
            </div>
            <div className="mobile-tools">
              <button
                className="icon-button"
                aria-label="查找页面"
                onClick={() => setCommands(true)}
              >
                <Search size={19} />
              </button>
              <Link className="icon-button" aria-label="设置" to="/settings/account">
                <Settings size={19} />
              </Link>
            </div>
            <span className="desktop-only muted">{identity.member.name}</span>
          </header>
          <Routes>
            <Route
              path="/"
              element={
                <Navigate to={identity.member.role === 'admin' ? '/team' : '/assistant'} replace />
              }
            />
            <Route path="/assistant" element={<Assistant />} />
            <Route path="/messages/:id" element={<SourcePage />} />
            <Route path="/work" element={<WorkPage />} />
            <Route path="/work/:id" element={<WorkDetail />} />
            <Route path="/reports" element={<ReportsPage />} />
            <Route path="/reports/:id" element={<ReportDetail />} />
            {identity.member.role === 'admin' && (
              <>
                <Route path="/team" element={<TeamPage />} />
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
                    <Route path="appearance" element={<AppearancePage />} />
                    <Route path="rules" element={<RulesPage />} />
                    {identity.member.role === 'admin' && (
                      <Route path="models" element={<ModelServices />} />
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
      {commands && (
        <Modal title="查找页面与操作" onClose={() => setCommands(false)}>
          <input
            autoFocus
            placeholder="搜索页面"
            aria-label="搜索页面"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="command-list">
            {[...allowed, ...allowedSettings]
              .filter((p) => p.title.includes(query))
              .map((p) => (
                <button
                  key={p.path}
                  onClick={() => {
                    navigate(p.path)
                    setCommands(false)
                    setQuery('')
                  }}
                >
                  {p.title}
                </button>
              ))}
          </div>
        </Modal>
      )}
    </Workspace.Provider>
  )
}
