import React, { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import { Avatar, Button, Icon, Modal, Tool } from './components'
import { Assistant, WorkPage, TeamPage, ModelsPage, ReportsPage } from './pages'
import { initialWork, nav, type Work } from './data'
import mark from '../../../../packages/ui-web/brand/logo.svg'

export default function App() {
  const [page, setPage] = useState('assistant')
  const [theme, setTheme] = useState('light')
  const navRef = useRef<HTMLElement>(null)
  const [navIndicator, setNavIndicator] = useState({ y: 0, height: 41 })
  const toggleTheme = (event: React.MouseEvent<HTMLButtonElement>) => {
    const apply = () =>
      flushSync(() => setTheme((current) => (current === 'light' ? 'dark' : 'light')))
    if (!document.startViewTransition || matchMedia('(prefers-reduced-motion: reduce)').matches) {
      apply()
      return
    }
    const rect = event.currentTarget.getBoundingClientRect()
    document.documentElement.style.setProperty('--theme-x', `${rect.x + rect.width / 2}px`)
    document.documentElement.style.setProperty('--theme-y', `${rect.y + rect.height / 2}px`)
    document.startViewTransition(apply)
  }
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [isMobile, setIsMobile] = useState(() => matchMedia('(max-width: 700px)').matches)
  useEffect(() => {
    const media = matchMedia('(max-width: 700px)')
    const update = () => setIsMobile(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  const [role, setRole] = useState('管理员')
  const [accountOpen, setAccountOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [command, setCommand] = useState(false)
  const [search, setSearch] = useState('')
  const [notes, setNotes] = useState(false)
  const [toast, setToast] = useState('')
  const [works, setWorks] = useState<Work[]>(initialWork)
  const navigate = (id: string) => {
    setPage(id)
    setMobileOpen(false)
    setCommand(false)
    setSettingsOpen(false)
  }
  const notify = (message: string) => setToast(message)
  const visibleNav = nav.filter((item) =>
    role === '管理员' ? item.id !== 'reports' : item.id !== 'team',
  )
  const pages = [
    ...visibleNav,
    ...(role === '管理员' ? [{ id: 'models', label: '模型服务管理', icon: 'Blocks' }] : []),
  ]
  useLayoutEffect(() => {
    const update = () => {
      const active = navRef.current?.querySelector<HTMLButtonElement>('[aria-current="page"]')
      if (active) setNavIndicator({ y: active.offsetTop, height: active.offsetHeight })
    }
    update()
    const observer = new ResizeObserver(update)
    if (navRef.current) observer.observe(navRef.current)
    return () => observer.disconnect()
  }, [page, role, collapsed])
  const title = pages.find((p) => p.id === page)?.label ?? '我的报告'
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute('content', theme === 'dark' ? '#101010' : '#f5f5f5')
  }, [theme])
  useEffect(() => {
    if (!toast) return
    const timeout = setTimeout(() => setToast(''), 2800)
    return () => clearTimeout(timeout)
  }, [toast])
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setCommand((v) => !v)
      }
      if (event.key === 'Escape') {
        setMobileOpen(false)
        setSettingsOpen(false)
        setAccountOpen(false)
      }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [])
  return (
    <div className={`app ${collapsed ? 'collapsed' : ''}`}>
      {mobileOpen && (
        <button
          className="mobile-scrim"
          aria-label="关闭导航"
          onClick={() => setMobileOpen(false)}
        />
      )}
      <aside
        className={`sidebar ${mobileOpen ? 'mobile-open' : ''}`}
        inert={isMobile && !mobileOpen}
      >
        <button className="brand" onClick={() => navigate('assistant')} aria-label="公司工作助手">
          <img src={mark} alt="" />
          <span>
            公司工作助手<small>团队的每一步，都在这里</small>
          </span>
        </button>
        <button
          className="nav-search"
          onClick={() => {
            setSearch('')
            setCommand(true)
          }}
          aria-label="搜索页面与操作"
        >
          <Icon name="Search" size={17} />
          <span>搜索与快捷操作</span>
          <kbd>⌘ K</kbd>
        </button>
        <div className="navigation-label">日常工作</div>
        <nav
          aria-label="主要导航"
          ref={navRef}
          style={
            {
              '--nav-y': `${navIndicator.y}px`,
              '--nav-height': `${navIndicator.height}px`,
              '--nav-visible': visibleNav.some((item) => item.id === page) ? 1 : 0,
            } as React.CSSProperties
          }
        >
          <span className="nav-indicator" aria-hidden="true" />
          {visibleNav.map((item) => (
            <button
              key={item.id}
              className={`nav-item ${page === item.id ? 'active' : ''}`}
              title={collapsed ? item.label : undefined}
              onClick={() => navigate(item.id)}
              aria-current={page === item.id ? 'page' : undefined}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
              {item.id === 'work' && (
                <small>{works.filter((w) => w.status !== '已完成').length}</small>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="settings-wrap">
            <button
              className={`nav-item ${page === 'models' ? 'active' : ''}`}
              onClick={() => setSettingsOpen(!settingsOpen)}
              aria-expanded={settingsOpen}
            >
              <Icon name="Settings2" />
              <span>系统设置</span>
              <Icon name="ChevronRight" size={14} />
            </button>
            {settingsOpen && (
              <div className="settings-menu popover">
                <span className="popover-label">偏好与管理</span>
                {role === '管理员' && (
                  <button onClick={() => navigate('models')}>
                    <Icon name="Blocks" />
                    模型服务管理
                    <Icon name="ChevronRight" size={14} />
                  </button>
                )}
                <button
                  onClick={(event) => {
                    toggleTheme(event)
                    setSettingsOpen(false)
                  }}
                >
                  <Icon name="SunMoon" />
                  切换外观<small>{theme === 'light' ? '深色' : '浅色'}</small>
                </button>
                <button
                  onClick={() => {
                    setNotes(true)
                    setSettingsOpen(false)
                  }}
                >
                  <Icon name="Info" />
                  关于这个原型
                </button>
              </div>
            )}
          </div>
          <div className="account-wrap">
            <button
              className="account"
              onClick={() => setAccountOpen(!accountOpen)}
              aria-expanded={accountOpen}
            >
              <Avatar name={role === '管理员' ? '管理员' : '林悦'} />
              <span>
                {role === '管理员' ? '管理员' : '林悦'}
                <small>{role === '管理员' ? '公司管理' : '个人工作空间'}</small>
              </span>
              <Icon name="ChevronsUpDown" size={14} />
            </button>
            {accountOpen && (
              <div className="role-menu popover">
                <span className="popover-label">原型角色预览</span>
                {['管理员', '用户'].map((r) => (
                  <button
                    key={r}
                    onClick={() => {
                      setRole(r)
                      setAccountOpen(false)
                      navigate('assistant')
                    }}
                  >
                    <Icon name={r === '管理员' ? 'ShieldCheck' : 'User'} />
                    {r}视角{role === r && <Icon name="Check" size={14} />}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </aside>
      <main className="workspace">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="tool desktop-collapse"
              aria-label="收起侧栏"
              onClick={() => setCollapsed(!collapsed)}
            >
              <Icon name="PanelLeft" />
            </button>
            <button
              className="tool mobile-toggle"
              aria-label="打开导航"
              onClick={() => setMobileOpen(true)}
            >
              <Icon name="Menu" />
            </button>
            <span className="breadcrumb-parent">{page === 'models' ? '系统设置' : '工作空间'}</span>
            <Icon name="ChevronRight" size={13} />
            <span>{title}</span>
          </div>
          <div className="topbar-actions">
            <button className="prototype-tag" onClick={() => setNotes(true)}>
              <span />
              交互原型
            </button>
            <span className="toolbar-separator" />
            <Tool
              label={theme === 'light' ? '切换深色' : '切换浅色'}
              icon={theme === 'light' ? 'Moon' : 'Sun'}
              onClick={toggleTheme}
            />
            <Tool
              label="通知"
              icon="Bell"
              onClick={() => notify('示例：今天有 2 项工作需要跟进')}
            />
          </div>
        </header>
        <div className={`content ${page === 'assistant' ? 'assistant-content' : ''}`} key={page}>
          {page === 'assistant' && (
            <Assistant
              navigate={navigate}
              notify={notify}
              works={works}
              setWorks={setWorks}
              role={role}
            />
          )}
          {page === 'work' && <WorkPage works={works} setWorks={setWorks} notify={notify} />}
          {page === 'team' && <TeamPage works={works} setWorks={setWorks} notify={notify} />}
          {page === 'models' && <ModelsPage notify={notify} />}
          {page === 'reports' && <ReportsPage notify={notify} />}
        </div>
      </main>
      {toast && (
        <div className="toast" role="status">
          <Icon name="Check" size={16} />
          {toast}
        </div>
      )}
      {command && (
        <Modal title="搜索与快捷操作" onClose={() => setCommand(false)}>
          <div className="command-search">
            <Icon name="Search" />
            <input
              autoFocus
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="前往页面，或寻找操作…"
            />
          </div>
          <div className="command-results">
            {pages
              .filter((p) => p.label.includes(search))
              .map((p) => (
                <button key={p.id} onClick={() => navigate(p.id)}>
                  <Icon name={p.icon} />
                  <span>{p.label}</span>
                  <Icon name="CornerDownLeft" size={15} />
                </button>
              ))}
            {pages.every((p) => !p.label.includes(search)) && (
              <p className="muted">没有找到相应页面</p>
            )}
          </div>
          <div className="command-footer">
            <kbd>esc</kbd> 关闭
          </div>
        </Modal>
      )}
      {notes && (
        <Modal title="让工作，自然地向前。" onClose={() => setNotes(false)}>
          <div className="prototype-notes">
            <p>这是公司工作助手的临时设计原型，使用示例数据，不连接现有业务接口。</p>
            <div>
              <Icon name="Palette" />
              <section>
                <h3>柔和的黑白灰</h3>
                <p>柔灰外框、独立内容画布、清晰正文。界面靠表面层级和结构建立秩序。</p>
              </section>
            </div>
            <div>
              <Icon name="PanelsTopLeft" />
              <section>
                <h3>让内容成为主角</h3>
                <p>输入、查询过程、结果与待确认操作各有自己的形态。列表更紧凑，详情就近展开。</p>
              </section>
            </div>
            <div>
              <Icon name="MousePointer2" />
              <section>
                <h3>可体验的交互</h3>
                <p>
                  试试滑动分段切换、按钮按压、浮层展开与明暗切换，也可以筛选列表、打开详情、创建示例工作。左下角可切换管理员与用户视角。
                </p>
              </section>
            </div>
            <a href="https://beui.dev/components/motion" target="_blank" rel="noreferrer">
              设计参考：Be UI <Icon name="ArrowUpRight" size={14} />
            </a>
          </div>
          <Button kind="primary full" onClick={() => setNotes(false)}>
            开始体验
            <Icon name="ArrowRight" size={16} />
          </Button>
        </Modal>
      )}
    </div>
  )
}
