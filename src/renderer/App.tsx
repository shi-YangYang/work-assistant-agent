import { useEffect, useRef, useState } from 'react'
import {
  AudioLines,
  ChevronRight,
  FileText,
  Layers3,
  Leaf,
  LockKeyhole,
  Mic,
  Plus,
  RefreshCw,
  Settings2,
  Sparkles,
  Square,
  ArrowLeft,
} from 'lucide-react'
import {
  ACTIVE_STATES,
  UNAVAILABLE_CAPABILITIES,
  type CoreStatus,
  type Meeting,
  type RecordingStatus,
} from '../shared/contracts'

const initialStatus: CoreStatus = {
  connection: 'starting',
  message: '正在连接本地核心…',
  capabilities: UNAVAILABLE_CAPABILITIES,
}
const idle: RecordingStatus = {
  meetingId: null,
  state: 'idle',
  elapsedMs: 0,
  deviceName: null,
  inputLevel: 0,
  error: null,
}
const labels: Record<string, string> = {
  idle: '准备开始',
  starting: '正在准备',
  recording: '录音中',
  stopping: '正在保存',
  completed: '已完成',
  interrupted: '录制中断',
  failed: '录制失败',
}
function duration(ms: number): string {
  const seconds = Math.floor(ms / 1000)
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
}
function date(value: string): string {
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

export function App(): React.JSX.Element {
  const [page, setPage] = useState<'meetings' | 'settings'>('meetings')
  const [status, setStatus] = useState<CoreStatus>(initialStatus)
  const [recording, setRecording] = useState<RecordingStatus>(idle)
  const [meetings, setMeetings] = useState<Meeting[]>([])
  const [loaded, setLoaded] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const [selected, setSelected] = useState<Meeting | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [uncertain, setUncertain] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const operationId = useRef<string | null>(null)
  const lastSession = useRef('')
  const audio = useRef<HTMLAudioElement>(null)
  const active = ACTIVE_STATES.includes(recording.state)
  const connected = status.connection === 'ready'
  const available = status.capabilities.find((item) => item.id === 'recording')?.available

  async function loadMeetings(offset = 0): Promise<void> {
    const result = await window.paa.listMeetings(offset)
    setLoaded(result.ok)
    if (result.ok) {
      setMeetings((previous) => (offset ? [...previous, ...result.meetings] : result.meetings))
      setHasMore(result.hasMore)
    } else setError(result.message)
  }
  async function openMeeting(id: string): Promise<void> {
    const result = await window.paa.getMeeting(id)
    if (result.ok) {
      setSelected(result.value)
      setPage('meetings')
    } else setError(result.message)
  }
  useEffect(() => {
    let alive = true
    const update = (value: CoreStatus): void => {
      if (alive) setStatus(value)
    }
    const unsubscribe = window.paa.onStatusChanged(update)
    const unsubscribeError = window.paa.onLifecycleError(setError)
    void window.paa
      .getStatus()
      .then(update)
      .catch(() =>
        update({
          ...initialStatus,
          connection: 'error',
          message: '桌面连接不可用，请重新启动应用。',
        }),
      )
    return () => {
      alive = false
      unsubscribe()
      unsubscribeError()
    }
  }, [])
  useEffect(() => {
    if (!connected) return
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    // Schedule the next query only after this one settles; page changes preserve capture.
    async function poll(): Promise<void> {
      try {
        const result = await window.paa.getRecordingStatus()
        if (!alive) return
        if (result.ok) {
          setRecording(result.value)
          setUncertain(false)
          const signature = `${result.value.meetingId}:${result.value.state}`
          if (lastSession.current !== signature) {
            lastSession.current = signature
            const list = await window.paa.listMeetings()
            if (!alive) return
            setLoaded(list.ok)
            if (list.ok) {
              setMeetings(list.meetings)
              setHasMore(list.hasMore)
            } else setError(list.message)
            if (result.value.meetingId && !ACTIVE_STATES.includes(result.value.state)) {
              const detail = await window.paa.getMeeting(result.value.meetingId)
              if (alive && detail.ok) setSelected(detail.value)
              operationId.current = null
            }
          }
        } else {
          setUncertain(true)
          setError(result.message)
        }
      } catch {
        if (alive) {
          setUncertain(true)
          setError('无法确认录音状态，请重新连接以恢复记录。')
        }
      } finally {
        if (alive)
          timer = setTimeout(() => {
            void poll()
          }, 400)
      }
    }
    lastSession.current = ''
    void poll()
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [connected, status.processId])

  async function start(): Promise<void> {
    audio.current?.pause()
    setBusy(true)
    setError('')
    setSelected(null)
    operationId.current ??= crypto.randomUUID()
    try {
      const result = await window.paa.startRecording(operationId.current)
      if (result.ok) {
        setRecording(result.value)
        setUncertain(false)
      } else {
        setError(result.message)
        setUncertain(result.code === 'timeout')
      }
    } catch {
      setUncertain(true)
      setError('开始请求未确认，正在查询当前录音状态。')
    } finally {
      setBusy(false)
    }
  }
  async function stop(): Promise<void> {
    if (!recording.meetingId) return
    setBusy(true)
    setError('')
    try {
      const result = await window.paa.stopRecording(recording.meetingId)
      if (result.ok) setRecording(result.value)
      else {
        setError(result.message)
        setUncertain(true)
      }
    } catch {
      setUncertain(true)
      setError('结束请求未确认，正在查询保存状态。')
    } finally {
      setBusy(false)
    }
  }
  async function retry(): Promise<void> {
    setRetrying(true)
    setError('')
    try {
      setStatus(await window.paa.retryCore())
    } catch {
      setError('重新连接未完成，请检查当前录音状态。')
    } finally {
      setRetrying(false)
    }
  }
  const connectionLabel = connected
    ? '本地核心已连接'
    : status.connection === 'starting'
      ? '正在连接本地核心'
      : '本地核心未连接'
  const interruptedConnection = active && !connected
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">
            <Leaf size={22} />
          </span>
          <div>
            <strong>个人工作助手</strong>
            <span>PERSONAL ASSISTANT</span>
          </div>
        </div>
        <div className="workspace-label">我的工作空间</div>
        <nav aria-label="主导航" className="navigation">
          <button
            className={`nav-item ${page === 'meetings' ? 'active' : ''}`}
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
              <strong>原始录音，留在本地</strong>
              <p>
                让每一次交流
                <br />
                成为可回顾的工作记忆。
              </p>
            </div>
          </div>
          <button
            className={`nav-item ${page === 'settings' ? 'active' : ''}`}
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
            录音预览版 <span>0.2</span>
          </span>
        </header>
        <main>
          {(error || recording.error || interruptedConnection) && (
            <div className="connection-notice error-notice" role="alert">
              <span>
                {interruptedConnection
                  ? '录音连接已中断，请重新连接以恢复已保存的内容。'
                  : error || recording.error?.message}
              </span>
              <button className="text-button" disabled={retrying} onClick={() => void retry()}>
                重新连接
              </button>
            </div>
          )}
          {active && (
            <section className="recording-card" aria-label="活动录音">
              <div className="recording-heading">
                <span
                  className={`recording-dot ${recording.state === 'recording' && connected ? 'live' : ''}`}
                />
                <strong>{interruptedConnection ? '录制中断' : labels[recording.state]}</strong>
                <span className="recording-time" aria-label="录音时长">
                  {duration(recording.elapsedMs)}
                </span>
              </div>
              <p>{recording.deviceName || '正在检查默认麦克风与本地存储…'}</p>
              <div className="recording-controls">
                <label>
                  输入音量{' '}
                  <meter aria-label="输入音量" min="0" max="1" value={recording.inputLevel} />
                </label>
                <button
                  className="secondary-button stop-button"
                  disabled={!connected || busy || recording.state === 'stopping'}
                  onClick={() => void stop()}
                >
                  <Square size={14} />
                  {recording.state === 'stopping' ? '正在保存…' : '结束会议'}
                </button>
              </div>
              <small>音频持续保存到本机。切换页面或最小化窗口可继续录音。</small>
            </section>
          )}
          {page === 'meetings' ? (
            <>
              <div className="page-heading">
                <div>
                  <p className="eyebrow">MEETING WORKSPACE</p>
                  <h1>留住讨论，理清下一步。</h1>
                  <p className="subtitle">记录真实声音，随时回到讨论发生的那一刻。</p>
                </div>
                <div className="meeting-action">
                  <button
                    className="primary-button"
                    disabled={!connected || !available || active || busy || uncertain}
                    onClick={() => void start()}
                  >
                    <Plus size={18} />
                    {busy && !active ? '正在准备…' : '开始会议'}
                  </button>
                  <span>使用系统默认麦克风</span>
                </div>
              </div>
              {!connected && (
                <div className="connection-notice" role="status">
                  {status.message}
                </div>
              )}
              {selected ? (
                <section className="meeting-detail">
                  <button
                    className="text-button"
                    onClick={() => {
                      audio.current?.pause()
                      setSelected(null)
                    }}
                  >
                    <ArrowLeft size={16} />
                    返回会议列表
                  </button>
                  <div className="section-heading">
                    <h2>{selected.title}</h2>
                    <span className={`meeting-state ${selected.status}`}>
                      {labels[selected.status]}
                    </span>
                  </div>
                  <p>{date(selected.startedAt || selected.createdAt)}</p>
                  <dl className="metadata">
                    <div>
                      <dt>录音时长</dt>
                      <dd>{duration(selected.durationMs)}</dd>
                    </div>
                    <div>
                      <dt>输入设备</dt>
                      <dd>{selected.deviceName || '未打开设备'}</dd>
                    </div>
                    <div>
                      <dt>音频格式</dt>
                      <dd>WAV · {selected.sampleRate} Hz · PCM16 单声道</dd>
                    </div>
                  </dl>
                  {selected.status === 'interrupted' && (
                    <p className="audio-warning">这场会议曾中断，以下音频只包含可恢复的部分。</p>
                  )}
                  {selected.status === 'failed' && (
                    <p className="audio-warning">
                      录音未成功保存，请检查麦克风、磁盘空间与目录权限后重试。
                    </p>
                  )}
                  {selected.audioError ? (
                    <p role="alert" className="audio-warning">
                      {selected.audioError}
                    </p>
                  ) : selected.audioAvailable ? (
                    active || busy || !connected ? (
                      <p className="audio-warning">录音期间或核心未连接时暂停回放。</p>
                    ) : (
                      <audio
                        ref={audio}
                        controls
                        preload="metadata"
                        src={`paa-audio://meeting/${selected.id}`}
                        aria-label="会议录音播放器"
                        onError={() => setError('无法播放录音，请检查文件是否缺失或损坏。')}
                      />
                    )
                  ) : (
                    <p>当前没有可播放的录音。</p>
                  )}
                  <div className="detail-future">
                    <Sparkles size={18} />
                    <span>本地转写与会议纪要尚未接入。</span>
                  </div>
                </section>
              ) : (
                <section className="meetings-section" aria-labelledby="meetings-title">
                  <div className="section-heading">
                    <h2 id="meetings-title">
                      我的会议 <span>{loaded ? meetings.length : '—'}</span>
                    </h2>
                    <button
                      className="text-button"
                      disabled={!connected}
                      onClick={() => void loadMeetings()}
                    >
                      刷新记录
                    </button>
                  </div>
                  {meetings.length ? (
                    <div className="meeting-list">
                      {meetings.map((meeting) => (
                        <button
                          className="meeting-row"
                          key={meeting.id}
                          onClick={() => void openMeeting(meeting.id)}
                        >
                          <span className="row-icon">
                            <AudioLines size={22} />
                          </span>
                          <span className="row-title">
                            <strong>{meeting.title}</strong>
                            <small>{date(meeting.createdAt)}</small>
                          </span>
                          <span>{duration(meeting.durationMs)}</span>
                          <span className={`meeting-state ${meeting.status}`}>
                            {labels[meeting.status]}
                          </span>
                          <ChevronRight size={16} />
                        </button>
                      ))}
                      {hasMore && (
                        <button
                          className="text-button"
                          onClick={() => void loadMeetings(meetings.length)}
                        >
                          加载更多
                        </button>
                      )}
                    </div>
                  ) : (
                    <div className="empty-state">
                      <div className="empty-art">
                        <div className="art-orbit" />
                        <div className="art-paper">
                          <AudioLines size={40} />
                        </div>
                      </div>
                      <h3>你的第一场会议，从这里开始</h3>
                      <p>点击开始会议，录下讨论。结束后可在这里回放。</p>
                      <div className="empty-label">
                        <span />
                        {loaded ? '暂无会议记录' : '等待会议记录加载'}
                      </div>
                    </div>
                  )}
                </section>
              )}
              <section className="foundation-banner">
                <span className="banner-icon">
                  <LockKeyhole size={20} />
                </span>
                <div>
                  <strong>先把原话留住</strong>
                  <p>录音保存到本机；本地转写和会议纪要将在后续接入。</p>
                </div>
              </section>
            </>
          ) : (
            <>
              <div className="page-heading">
                <div>
                  <p className="eyebrow">WORKSPACE SETTINGS</p>
                  <h1>为下一次会议做好准备。</h1>
                  <p className="subtitle">查看连接与录音准备状态。</p>
                </div>
              </div>
              <section className="settings-card">
                <div className="settings-card-heading">
                  <span className="settings-icon">
                    <Settings2 size={22} />
                  </span>
                  <div>
                    <h2>本地核心</h2>
                    <p>负责本地采集、保存与会议历史。</p>
                  </div>
                  <span className={`status-pill ${connected ? 'ready' : 'pending'}`}>
                    {connectionLabel}
                  </span>
                </div>
                <div className="core-detail" role="status">
                  <strong>{status.message}</strong>
                  <p>
                    {connected
                      ? `Python ${status.pythonVersion} · 点击开始会议时检查麦克风。`
                      : '请检查应用运行环境，完成后重新连接。'}
                  </p>
                </div>
                <div className="settings-card-footer">
                  <span>重连前会保护当前录音。</span>
                  <button
                    className="secondary-button"
                    disabled={retrying || status.connection === 'starting'}
                    onClick={() => void retry()}
                  >
                    <RefreshCw size={15} />
                    {retrying ? '连接中…' : '重新连接'}
                  </button>
                </div>
              </section>
              <section className="settings-card capabilities">
                <div className="capability-heading">
                  <h2>会议能力</h2>
                  <p>录音就绪后，仍需成功打开默认麦克风才能开始采集。</p>
                </div>
                {[
                  {
                    id: 'recording',
                    name: '持续录音',
                    description: '默认麦克风 · 本地保存与回放',
                    icon: Mic,
                  },
                  {
                    id: 'transcription',
                    name: '本地转写',
                    description: '后续提供完整文字记录',
                    icon: AudioLines,
                  },
                  {
                    id: 'summary',
                    name: '会议纪要',
                    description: '后续梳理讨论要点与行动项',
                    icon: Sparkles,
                  },
                ].map(({ id, name, description, icon: Icon }) => (
                  <div className="capability-row" key={id}>
                    <Icon size={20} />
                    <div>
                      <strong>{name}</strong>
                      <p>{description}</p>
                    </div>
                    <span className="unavailable-badge">
                      {status.capabilities.find((item) => item.id === id)?.available
                        ? '已就绪'
                        : id === 'recording'
                          ? '未就绪'
                          : '尚未接入'}
                    </span>
                  </div>
                ))}
              </section>
              <p className="settings-footnote">
                <LockKeyhole size={15} />
                仅在开始会议后采集麦克风。当前无需模型或密钥。
              </p>
            </>
          )}
          <footer className="workspace-footer">
            <span className={`connection-dot ${connected ? 'connected' : ''}`} />
            <span>{connectionLabel}</span>
            <span className="footer-separator">·</span>
            <span>音频保存在本机</span>
          </footer>
        </main>
      </div>
    </div>
  )
}
