import { useEffect, useState } from 'react'
import {
  ArrowRight,
  AudioLines,
  Check,
  ChevronRight,
  CircleHelp,
  FileText,
  Layers3,
  Leaf,
  LockKeyhole,
  Mic,
  Monitor,
  Plus,
  RefreshCw,
  Settings2,
  Sparkles,
  Waves,
} from 'lucide-react'
import { UNAVAILABLE_CAPABILITIES, type CoreStatus } from '../shared/contracts'

const initialStatus: CoreStatus = {
  connection: 'starting',
  message: '正在连接本地核心…',
  capabilities: UNAVAILABLE_CAPABILITIES,
}

export function App(): React.JSX.Element {
  const [page, setPage] = useState<'meetings' | 'settings'>('meetings')
  const [status, setStatus] = useState<CoreStatus>(initialStatus)
  const [meetingsLoaded, setMeetingsLoaded] = useState(false)
  const [listError, setListError] = useState('')
  const [retrying, setRetrying] = useState(false)

  useEffect(() => {
    let active = true
    const update = (next: CoreStatus): void => {
      if (active) setStatus(next)
    }
    const unsubscribe = window.paa.onStatusChanged(update)
    void window.paa
      .getStatus()
      .then(update)
      .catch(() => {
        update({
          ...initialStatus,
          connection: 'error',
          message: '桌面连接不可用，请重新启动应用。',
        })
      })
    return () => {
      active = false
      unsubscribe()
    }
  }, [])

  useEffect(() => {
    let active = true
    if (status.connection === 'ready') {
      void window.paa
        .listMeetings()
        .then((result) => {
          if (!active) return
          setMeetingsLoaded(result.ok)
          setListError(result.ok ? '' : result.message)
        })
        .catch(() => {
          if (active) {
            setMeetingsLoaded(false)
            setListError('暂时无法读取会议记录，请重新连接本地核心。')
          }
        })
    }
    return () => {
      active = false
    }
  }, [status.connection, status.processId])

  const retry = async (): Promise<void> => {
    setRetrying(true)
    try {
      setStatus(await window.paa.retryCore())
    } catch {
      setStatus({ ...initialStatus, connection: 'error', message: '重试失败，请重新启动应用。' })
    } finally {
      setRetrying(false)
    }
  }
  const connected = status.connection === 'ready'
  const connectionLabel = connected
    ? '本地核心已连接'
    : status.connection === 'starting'
      ? '正在连接本地核心'
      : '本地核心未连接'

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">
            <Leaf size={22} strokeWidth={1.8} />
          </span>
          <div>
            <strong>个人工作助手</strong>
            <span>PERSONAL ASSISTANT</span>
          </div>
        </div>
        <div className="workspace-label">我的工作空间</div>
        <nav aria-label="主导航" className="navigation">
          <button
            className={page === 'meetings' ? 'nav-item active' : 'nav-item'}
            aria-current={page === 'meetings' ? 'page' : undefined}
            onClick={() => setPage('meetings')}
          >
            <AudioLines size={19} />
            <span>会议记录</span>
            <span className="nav-dot" />
          </button>
          <div className="nav-item future">
            <FileText size={19} />
            <span>员工周报</span>
            <small>后续</small>
          </div>
          <div className="nav-item future">
            <Layers3 size={19} />
            <span>长期记忆</span>
            <small>后续</small>
          </div>
        </nav>
        <div className="sidebar-bottom">
          <div className="local-note">
            <LockKeyhole size={17} />
            <div>
              <strong>从本地开始</strong>
              <p>
                让每一次交流
                <br />
                成为可回顾的工作记忆。
              </p>
            </div>
          </div>
          <button
            className={page === 'settings' ? 'nav-item active' : 'nav-item'}
            aria-current={page === 'settings' ? 'page' : undefined}
            onClick={() => setPage('settings')}
          >
            <Settings2 size={19} />
            <span>设置</span>
          </button>
          <div className="profile">
            <span className="avatar">我</span>
            <div>
              <strong>个人工作空间</strong>
              <span>本地 · 开发预览</span>
            </div>
          </div>
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <div>
            工作空间 <ChevronRight size={14} />
            <strong>{page === 'meetings' ? '会议记录' : '设置'}</strong>
          </div>
          <span className="preview-badge">
            基础预览版 <span>0.1</span>
          </span>
        </header>
        <main>
          {page === 'meetings' ? (
            <>
              <div className="page-heading">
                <div>
                  <p className="eyebrow">MEETING WORKSPACE</p>
                  <h1>留住讨论，理清下一步。</h1>
                  <p className="subtitle">在这里记录会议、回顾决策，让重要的信息有迹可循。</p>
                </div>
                <div className="meeting-action">
                  <button className="primary-button" disabled aria-describedby="recording-hint">
                    <Plus size={18} />
                    开始会议
                  </button>
                  <span id="recording-hint">录音功能尚未接入</span>
                </div>
              </div>
              <section className="foundation-banner" aria-label="当前开发阶段">
                <span className="banner-icon">
                  <Sparkles size={20} />
                </span>
                <div>
                  <strong>工作空间已建立，会议能力即将接入</strong>
                  <p>当前为应用骨架，可查看本地核心状态；录音、转写与纪要仍在后续计划中。</p>
                </div>
                <button className="text-button" onClick={() => setPage('settings')}>
                  查看准备状态 <ArrowRight size={16} />
                </button>
              </section>
              {!connected && (
                <div className="connection-notice" role="status">
                  <CircleHelp size={17} />
                  <span>{status.message}</span>
                  <button className="text-button" onClick={() => setPage('settings')}>
                    前往设置 <ArrowRight size={14} />
                  </button>
                </div>
              )}
              <section className="meetings-section" aria-labelledby="meetings-title">
                <div className="section-heading">
                  <h2 id="meetings-title">
                    我的会议 <span>{connected && meetingsLoaded ? '0' : '—'}</span>
                  </h2>
                  <span className="section-caption">让重要的讨论，沉淀下来</span>
                </div>
                <div className="empty-state">
                  <div className="empty-art" aria-hidden="true">
                    <div className="art-orbit" />
                    <div className="art-paper">
                      <div className="art-paper-header">
                        <AudioLines size={26} />
                        <span />
                      </div>
                      <i />
                      <i />
                      <i />
                      <div className="art-check">
                        <Check size={13} />
                        <span />
                      </div>
                    </div>
                    <div className="art-mic">
                      <Mic size={22} />
                    </div>
                    <div className="art-spark">
                      <Sparkles size={16} />
                    </div>
                  </div>
                  <h3>
                    {connected && meetingsLoaded
                      ? '你的第一场会议，从这里开始'
                      : '会议工作空间已就位'}
                  </h3>
                  <p>
                    {connected && meetingsLoaded
                      ? '这里还没有会议记录。会议功能接入后，'
                      : listError || '本地核心连接后，即可读取会议记录。'}
                    <br />
                    完整转写、关键决策和行动项将在这里有序归档。
                  </p>
                  <div className="empty-label">
                    <span />
                    {connected && meetingsLoaded ? '暂无会议记录' : '等待本地核心连接'}
                  </div>
                </div>
              </section>
              <section className="workflow-section" aria-labelledby="workflow-title">
                <div className="section-heading">
                  <h2 id="workflow-title">从对话，到行动</h2>
                  <span className="section-caption">后续会议体验</span>
                </div>
                <div className="workflow-grid">
                  <article>
                    <span className="step-icon">
                      <Mic size={19} />
                    </span>
                    <span className="step-number">01</span>
                    <h3>专注讨论</h3>
                    <p>
                      持续记录会议音频，
                      <br />
                      让你把注意力留给交流。
                    </p>
                    <small>待接入 · 录音</small>
                  </article>
                  <article>
                    <span className="step-icon">
                      <Waves size={19} />
                    </span>
                    <span className="step-number">02</span>
                    <h3>保留原话</h3>
                    <p>
                      本地转写、保留完整记录，
                      <br />
                      随时找回讨论的上下文。
                    </p>
                    <small>待接入 · 转写</small>
                  </article>
                  <article>
                    <span className="step-icon">
                      <Sparkles size={19} />
                    </span>
                    <span className="step-number">03</span>
                    <h3>明确下一步</h3>
                    <p>
                      会后整理决策与行动项，
                      <br />
                      把讨论推进成具体工作。
                    </p>
                    <small>待接入 · 会议纪要</small>
                  </article>
                </div>
              </section>
            </>
          ) : (
            <>
              <div className="page-heading">
                <div>
                  <p className="eyebrow">WORKSPACE SETTINGS</p>
                  <h1>为下一次会议做好准备。</h1>
                  <p className="subtitle">查看本地运行状态，了解当前可用的能力。</p>
                </div>
              </div>
              <section className="settings-card" aria-labelledby="core-title">
                <div className="settings-card-heading">
                  <span className="settings-icon">
                    <Monitor size={22} />
                  </span>
                  <div>
                    <h2 id="core-title">本地核心</h2>
                    <p>为会议记录与后续处理提供本地运行基础。</p>
                  </div>
                  <span className={`status-pill ${connected ? 'ready' : 'pending'}`}>
                    <span />
                    {connectionLabel}
                  </span>
                </div>
                <div className="core-detail" role="status">
                  <strong>{status.message}</strong>
                  <p>
                    {connected
                      ? `Python ${status.pythonVersion} · 当前无需模型、密钥或麦克风权限。`
                      : '请按照项目 README 准备 Python 3.12 环境，完成后可在此重试。'}
                  </p>
                </div>
                <div className="settings-card-footer">
                  <span>核心连接成功，仅表示本地服务可用。</span>
                  <button
                    className="secondary-button"
                    disabled={retrying || status.connection === 'starting'}
                    onClick={() => void retry()}
                  >
                    <RefreshCw size={15} className={retrying ? 'spinning' : ''} />
                    {retrying || status.connection === 'starting' ? '连接中…' : '重新连接'}
                  </button>
                </div>
              </section>
              <section className="settings-card capabilities" aria-labelledby="capability-title">
                <div className="capability-heading">
                  <h2 id="capability-title">会议能力</h2>
                  <p>以下能力将在后续版本逐步接入。</p>
                </div>
                {[
                  { icon: Mic, name: '持续录音', description: '记录完整会议音频，支持后续回顾。' },
                  {
                    icon: Waves,
                    name: '本地转写',
                    description: '将会议音频整理为可检索的完整文字。',
                  },
                  {
                    icon: Sparkles,
                    name: '会议纪要',
                    description: '会后梳理讨论要点、决策与行动项。',
                  },
                ].map(({ icon: Icon, name, description }) => (
                  <div className="capability-row" key={name}>
                    <Icon size={20} />
                    <div>
                      <strong>{name}</strong>
                      <p>{description}</p>
                    </div>
                    <span className="unavailable-badge">尚未接入</span>
                  </div>
                ))}
              </section>
              <p className="settings-footnote">
                <LockKeyhole size={15} />
                当前不会采集麦克风、下载模型或向外部模型发送数据。
              </p>
            </>
          )}
          <footer className="workspace-footer">
            <span className={`connection-dot ${connected ? 'connected' : ''}`} />
            <span>{connectionLabel}</span>
            <span className="footer-separator">·</span>
            <span>会议能力建设中</span>
          </footer>
        </main>
      </div>
    </div>
  )
}
