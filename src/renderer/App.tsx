import { ApiModelSettings } from './ModelSettings'
import { MeetingMinutes } from './MeetingMinutes'
import { ModelSettings, Transcript } from './Transcription'
import type { ModelState } from '../shared/contracts'
import { useEffect, useRef, useState } from 'react'
import {
  AudioLines,
  ChevronRight,
  Leaf,
  Mic,
  Plus,
  RefreshCw,
  Settings2,
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
  message: '正在连接…',
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
  const [model, setModel] = useState<ModelState | null>(null)
  const [modelRefresh, setModelRefresh] = useState(0)
  useEffect(() => {
    if (!connected) return
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    async function pollModel(): Promise<void> {
      try {
        const result = await window.paa.getTranscriptionModel()
        if (alive && result.ok) setModel(result.value)
      } finally {
        if (alive)
          timer = setTimeout(() => {
            void pollModel()
          }, 1000)
      }
    }
    void pollModel()
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [connected, status.processId, modelRefresh])
  const connectionLabel = connected
    ? '已连接'
    : status.connection === 'starting'
      ? '连接中'
      : '未连接'
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
        </nav>
        <div className="sidebar-bottom">
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
              <p>{recording.deviceName || '正在准备录音…'}</p>
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
              <small>切换页面或最小化窗口后，录音会继续。</small>
            </section>
          )}
          {active && connected && recording.meetingId && (
            <Transcript
              key={recording.meetingId}
              meetingId={recording.meetingId}
              modelReady={model?.state === 'ready'}
              playable={false}
            />
          )}
          {page === 'meetings' ? (
            <>
              <div className="page-heading">
                <div>
                  <h1>会议记录</h1>
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
                  <span>
                    {model?.state === 'ready' ? '录音时自动转写' : '可先录音，下载模型后补转写'}
                  </span>
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
                      <dt>麦克风</dt>
                      <dd>{selected.deviceName || '未打开设备'}</dd>
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
                      <p className="audio-warning">录音或重新连接期间暂停回放。</p>
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
                  {connected && (
                    <Transcript
                      key={selected.id}
                      meetingId={selected.id}
                      modelReady={model?.state === 'ready'}
                      playable={selected.audioAvailable && !active && !busy}
                      onSeek={(ms) => {
                        if (audio.current && !active) {
                          audio.current.currentTime = ms / 1000
                          void audio.current.play().catch(() => setError('无法播放录音。'))
                        }
                      }}
                    />
                  )}
                  {connected && (
                    <MeetingMinutes
                      key={`summary-${selected.id}`}
                      meetingId={selected.id}
                      playable={selected.audioAvailable && !active && !busy}
                      onSeek={(ms) => {
                        if (audio.current && !active) {
                          audio.current.currentTime = ms / 1000
                          void audio.current.play().catch(() => setError('无法播放录音。'))
                        }
                      }}
                    />
                  )}
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
                      <h3>{loaded ? '暂无会议记录' : '正在加载会议记录'}</h3>
                      <p>点击「开始会议」录音，结束后可在这里查看和回放。</p>
                    </div>
                  )}
                </section>
              )}
            </>
          ) : (
            <>
              <div className="page-heading">
                <div>
                  <h1>设置</h1>
                </div>
              </div>
              <section className="settings-card">
                <div className="settings-card-heading">
                  <span className="settings-icon">
                    <Settings2 size={22} />
                  </span>
                  <div>
                    <h2>应用状态</h2>
                  </div>
                  <span className={`status-pill ${connected ? 'ready' : 'pending'}`}>
                    {connectionLabel}
                  </span>
                </div>
                <div className="core-detail" role="status">
                  <strong>{status.message}</strong>
                </div>
                <div className="settings-card-footer">
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
              <ApiModelSettings />
              <ModelSettings model={model} refresh={() => setModelRefresh((value) => value + 1)} />
              <section className="settings-card capabilities">
                <div className="capability-heading">
                  <h2>录音与转写</h2>
                </div>
                {[
                  {
                    id: 'recording',
                    name: '持续录音',
                    description: '使用默认麦克风录音',
                    icon: Mic,
                  },
                  {
                    id: 'transcription',
                    name: '本地转写',
                    description: '离线生成带时间的文字记录',
                    icon: AudioLines,
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
                        : '未就绪'}
                    </span>
                  </div>
                ))}
              </section>
            </>
          )}
          <footer className="workspace-footer">
            <span className={`connection-dot ${connected ? 'connected' : ''}`} />
            <span>{connectionLabel}</span>
          </footer>
        </main>
      </div>
    </div>
  )
}
