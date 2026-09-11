import { Appearance, CommandPalette, pageLabels, useTheme, type Page } from './Navigation'
import { MeetingWorkspace } from './MeetingWorkspace'
import { MeetingProcessingState } from './MeetingProcessingState'
import { type AudioPlayerHandle } from './AudioPlayer'
import { ApiModelSettings } from './ModelSettings'
import { ModelSettings, Transcript } from './Transcription'
import type { ModelState } from '../shared/contracts'
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AudioLines,
  ChevronRight,
  Command,
  Monitor,
  Database,
  Mic,
  Plus,
  Pause,
  Play,
  Settings2,
  Square,
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
  pausing: '正在暂停',
  paused: '已暂停',
  resuming: '正在继续',
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
  const [page, setPage] = useState<Page>('meetings')
  const [theme, setTheme] = useTheme()
  const [commandOpen, setCommandOpen] = useState(false)
  const heading = useRef<HTMLHeadingElement>(null)
  const route = useRef<Page>('meetings')
  const listViewport = useRef<HTMLDivElement>(null)
  const listScroll = useRef(0)
  const [status, setStatus] = useState<CoreStatus>(initialStatus)
  const [recording, setRecording] = useState<RecordingStatus>(idle)
  const [meetings, setMeetings] = useState<Meeting[]>([])
  const [listBusy, setListBusy] = useState(false)
  const [listRefreshVersion, setListRefreshVersion] = useState(0)
  const [loaded, setLoaded] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const [selected, setSelected] = useState<Meeting | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [uncertain, setUncertain] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const operationId = useRef<string | null>(null)
  const recordingVersion = useRef(0)
  const lastSession = useRef('')
  const selectionGeneration = useRef(0)
  const audio = useRef<AudioPlayerHandle>(null)
  const active = ACTIVE_STATES.includes(recording.state)
  const connected = status.connection === 'ready'
  const available = status.capabilities.find((item) => item.id === 'recording')?.available

  const navigate = useCallback((next: Page): void => {
    audio.current?.pause()
    selectionGeneration.current++
    if (route.current === 'meetings') listScroll.current = listViewport.current?.scrollTop || 0
    route.current = next
    setCommandOpen(false)
    setPage(next)
    requestAnimationFrame(() => {
      heading.current?.focus()
      if (next === 'meetings' && listViewport.current)
        listViewport.current.scrollTop = listScroll.current
    })
  }, [])
  useEffect(() => {
    const keyboard = (event: KeyboardEvent): void => {
      if (
        (event.metaKey || event.ctrlKey) &&
        event.key.toLowerCase() === 'k' &&
        !event.altKey &&
        !(event.target as HTMLElement).closest(
          'input, textarea, select, [contenteditable="true"], .audio-player',
        )
      ) {
        event.preventDefault()
        setCommandOpen((value) => !value)
      }
    }
    document.addEventListener('keydown', keyboard)
    return () => document.removeEventListener('keydown', keyboard)
  }, [])
  async function loadMeetings(offset = 0): Promise<void> {
    setListBusy(true)
    try {
      const result = await window.paa.listMeetings(offset)
      setLoaded(result.ok)
      if (result.ok) {
        setMeetings((previous) => (offset ? [...previous, ...result.meetings] : result.meetings))
        if (!offset) setListRefreshVersion((version) => version + 1)
        setHasMore(result.hasMore)
      } else setError(result.message)
    } catch {
      setError('无法读取会议列表，请重新连接后重试。')
    } finally {
      setListBusy(false)
    }
  }
  async function openMeeting(id: string): Promise<void> {
    if (active && id === recording.meetingId) {
      navigate('current')
      return
    }
    audio.current?.pause()
    const generation = ++selectionGeneration.current
    try {
      const result = await window.paa.getMeeting(id)
      if (generation !== selectionGeneration.current) return
      if (result.ok) {
        setSelected(result.value)
        navigate('meeting')
      } else setError(result.message)
    } catch {
      if (generation === selectionGeneration.current) setError('无法打开会议，请重新连接后重试。')
    }
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
        const selection = selectionGeneration.current
        const version = recordingVersion.current
        const result = await window.paa.getRecordingStatus()
        if (!alive || version !== recordingVersion.current) return
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
              setMeetings((previous) => [
                ...list.meetings,
                ...previous.filter(
                  (meeting) => !list.meetings.some((item) => item.id === meeting.id),
                ),
              ])
              setHasMore(list.hasMore)
            } else setError(list.message)
            if (result.value.meetingId && !ACTIVE_STATES.includes(result.value.state)) {
              const detail = await window.paa.getMeeting(result.value.meetingId)
              if (
                alive &&
                detail.ok &&
                route.current === 'current' &&
                selection === selectionGeneration.current
              ) {
                setSelected(detail.value)
                navigate('meeting')
              }
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
    // Navigation is read through route so capture polling never restarts on a page change.
  }, [connected, status.processId, navigate])

  async function start(): Promise<void> {
    recordingVersion.current++
    audio.current?.pause()
    setBusy(true)
    setError('')
    selectionGeneration.current++
    operationId.current ??= crypto.randomUUID()
    try {
      const result = await window.paa.startRecording(operationId.current)
      if (result.ok) {
        setRecording(result.value)
        setUncertain(false)
        setSelected(null)
        navigate('current')
      } else {
        setError(result.message)
        setUncertain(result.code === 'timeout')
      }
    } catch {
      setUncertain(true)
      setError('开始请求未确认，正在查询当前录音状态。')
    } finally {
      recordingVersion.current++
      setBusy(false)
    }
  }
  async function stop(): Promise<void> {
    if (!recording.meetingId) return
    recordingVersion.current++
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
      recordingVersion.current++
      setBusy(false)
    }
  }
  async function pauseOrResume(): Promise<void> {
    if (!recording.meetingId || busy) return
    recordingVersion.current++
    setBusy(true)
    setError('')
    try {
      const result = await (recording.state === 'paused'
        ? window.paa.resumeRecording(recording.meetingId)
        : window.paa.pauseRecording(recording.meetingId))
      if (result.ok) setRecording(result.value)
      else setError(result.message)
    } catch {
      setUncertain(true)
      setError('操作尚未确认，正在查询录音状态。')
    } finally {
      recordingVersion.current++
      setBusy(false)
    }
  }
  async function retry(): Promise<void> {
    audio.current?.pause()
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
      } catch {
        // The connection notice offers recovery; keep the last known download state.
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
  const canStart = connected && !!available && !active && !busy && !uncertain && !retrying
  const navItems = [
    { page: 'meetings' as const, icon: AudioLines },
    ...(active ? [{ page: 'current' as const, icon: Mic }] : []),
    { page: 'services' as const, icon: Settings2 },
    { page: 'local-model' as const, icon: Database },
    { page: 'appearance' as const, icon: Monitor },
  ]
  const commands = [
    ...navItems.map((item) => ({
      id: item.page,
      label: pageLabels[item.page],
      detail: ['services', 'local-model', 'appearance'].includes(item.page) ? '设置' : '工作空间',
      // This callback runs only after a command is selected, never during render.
      // eslint-disable-next-line react-hooks/refs
      run: () => navigate(item.page),
    })),
    ...(!active
      ? [
          {
            id: 'current',
            label: '当前会议',
            detail: '尚无活动录音',
            disabled: true,
            run: () => {},
          },
        ]
      : []),
    {
      id: 'start',
      label: '开始会议',
      detail: active ? '已有活动录音' : canStart ? '使用默认麦克风录音' : '等待录音就绪',
      disabled: !canStart,
      run: () => void start(),
    },
  ]
  const recordingControls = (
    <div className="recording-controls">
      <button
        className="secondary-button"
        disabled={!connected || busy || !['recording', 'paused'].includes(recording.state)}
        onClick={() => void pauseOrResume()}
      >
        {recording.state === 'paused' ? <Play size={15} /> : <Pause size={15} />}
        {recording.state === 'paused'
          ? '继续录音'
          : recording.state === 'pausing'
            ? '正在暂停…'
            : recording.state === 'resuming'
              ? '正在继续…'
              : '暂停录音'}
      </button>
      <button
        className="secondary-button stop-button"
        disabled={!connected || busy || recording.state === 'stopping'}
        onClick={() => void stop()}
      >
        <Square size={14} />
        {recording.state === 'stopping' ? '正在保存…' : '结束会议'}
      </button>
    </div>
  )
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">
            <AudioLines size={22} />
          </span>
          <strong>个人工作助手</strong>
        </div>
        <button className="command-trigger" onClick={() => setCommandOpen(true)}>
          <Command size={16} />
          <span>查找页面与操作</span>
          <kbd>{navigator.platform.includes('Mac') ? '⌘ K' : 'Ctrl K'}</kbd>
        </button>
        <nav aria-label="主导航" className="navigation">
          {navItems.map(({ page: target, icon: Icon }, index) => (
            <div key={target}>
              {index === 0 && <p className="workspace-label">工作空间</p>}
              {target === 'services' && <p className="workspace-label settings-label">设置</p>}
              <button
                className={`nav-item ${page === target || (page === 'meeting' && target === 'meetings') ? 'active' : ''}`}
                aria-current={
                  page === target || (page === 'meeting' && target === 'meetings')
                    ? 'page'
                    : undefined
                }
                onClick={() => navigate(target)}
              >
                <Icon size={18} />
                <span>{pageLabels[target]}</span>
                {target === 'current' && <span className="recording-dot" />}
              </button>
            </div>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="connection-status">
            <span className={`connection-dot ${connected ? 'connected' : ''}`} />
            <span>{connectionLabel}</span>
            <button
              className="text-button"
              disabled={retrying || status.connection === 'starting'}
              onClick={() => void retry()}
            >
              {retrying ? '正在连接…' : '重新连接'}
            </button>
          </div>
          <small>录音与文字保存在本机</small>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <span>
            {['services', 'local-model', 'appearance'].includes(page) ? '设置' : '工作空间'}
          </span>
          <ChevronRight size={14} />
          <strong>{pageLabels[page]}</strong>
        </header>
        <main>
          {(error ||
            recording.error ||
            interruptedConnection ||
            !connected ||
            status.storageError) && (
            <div className="connection-notice error-notice" role="alert">
              <span>
                {interruptedConnection
                  ? '录音连接已中断，请重新连接以恢复已保存的内容。'
                  : error || recording.error?.message || status.storageError || status.message}
              </span>
            </div>
          )}
          <div className="page-heading">
            <div>
              <h1 ref={heading} tabIndex={-1}>
                {page === 'meeting' && selected ? selected.title : pageLabels[page]}
              </h1>
              {page === 'meetings' && <p>保留讨论，回顾决定与下一步。</p>}
              {page === 'services' && <p>管理生成会议纪要所使用的服务。</p>}
              {page === 'current' && (
                <p>
                  {recording.deviceName || '正在准备麦克风'} ·{' '}
                  {available ? '麦克风已就绪' : '等待录音设备'}
                </p>
              )}
            </div>
            {['meetings', 'current', 'meeting'].includes(page) && (
              <div className="meeting-action">
                <button
                  className="primary-button"
                  disabled={!canStart}
                  onClick={() => void start()}
                >
                  <Plus size={18} />
                  {busy && !active ? '正在准备…' : '开始会议'}
                </button>
                {page === 'meetings' && (
                  <small>
                    {available ? '麦克风已就绪' : '麦克风暂不可用'} ·{' '}
                    {model?.state === 'ready' ? '录音时自动转写' : '可先录音，准备模型后补转写'}
                  </small>
                )}
              </div>
            )}
          </div>
          <div ref={listViewport} hidden={page !== 'meetings'} className="page-content list-page">
            <section className="meetings-section" aria-labelledby="meetings-title">
              <div className="section-heading">
                <h2 id="meetings-title">
                  我的会议 <span>{loaded ? meetings.length : '—'}</span>
                </h2>
                <button
                  className="text-button"
                  disabled={!connected || listBusy}
                  onClick={() => void loadMeetings()}
                >
                  {listBusy ? '正在刷新…' : '刷新记录'}
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
                        <AudioLines size={21} />
                      </span>
                      <span className="row-title">
                        <strong>{meeting.title}</strong>
                        <small>{date(meeting.createdAt)}</small>
                      </span>
                      <span>{duration(meeting.durationMs)}</span>
                      <span className="row-state">
                        <span className={`meeting-state ${meeting.status}`}>
                          {labels[meeting.status]}
                        </span>
                        <MeetingProcessingState
                          meetingId={meeting.id}
                          visible={page === 'meetings'}
                          connected={connected}
                          state={meeting.status}
                          refreshVersion={listRefreshVersion}
                        />
                      </span>
                      <ChevronRight size={16} />
                    </button>
                  ))}
                  {hasMore && (
                    <button
                      className="text-button"
                      disabled={!connected}
                      onClick={() => void loadMeetings(meetings.length)}
                    >
                      加载更多
                    </button>
                  )}
                </div>
              ) : (
                <div className="empty-state">
                  <AudioLines size={38} />
                  <h3>{loaded ? '暂无会议记录' : '正在加载会议记录'}</h3>
                  <p>点击「开始会议」录音，结束后可在这里查看和回放。</p>
                </div>
              )}
            </section>
          </div>
          {active && (
            <div hidden={page !== 'current'} className="page-content current-page">
              <section className="recording-card" aria-label="当前录音">
                <div className="recording-heading">
                  <span
                    className={`recording-dot ${recording.state === 'recording' && connected ? 'live' : ''}`}
                  />
                  <strong>{interruptedConnection ? '录制中断' : labels[recording.state]}</strong>
                  <span className="recording-time" aria-label="录音时长">
                    {duration(recording.elapsedMs)}
                  </span>
                </div>
                <label className="input-meter">
                  输入音量{' '}
                  <meter aria-label="输入音量" min="0" max="1" value={recording.inputLevel} />
                </label>
                {recordingControls}
                <small>
                  {recording.state === 'paused'
                    ? '暂停期间不采集声音，继续后接着录制。'
                    : '切换页面或最小化窗口后，录音会继续。'}
                </small>
              </section>
              {connected && recording.meetingId && (
                <Transcript
                  key={recording.meetingId}
                  meetingId={recording.meetingId}
                  modelReady={model?.state === 'ready'}
                  playable={false}
                  visible={page === 'current'}
                  live
                />
              )}
            </div>
          )}
          {page === 'meeting' && selected && (
            <MeetingWorkspace
              key={selected.id}
              meeting={selected}
              audioRef={audio}
              connected={connected}
              playable={!active && !busy && !retrying && connected}
              modelReady={model?.state === 'ready'}
              onBack={() => navigate('meetings')}
              onServices={() => navigate('services')}
            />
          )}
          <div hidden={page !== 'services'} className="page-content settings-page">
            <ApiModelSettings visible={page === 'services'} />
          </div>
          <div hidden={page !== 'local-model'} className="page-content settings-page">
            <ModelSettings model={model} refresh={() => setModelRefresh((value) => value + 1)} />
          </div>
          <div hidden={page !== 'appearance'} className="page-content settings-page">
            <Appearance theme={theme} onChange={setTheme} />
          </div>
          {active && page !== 'current' && (
            <section className="recording-bar" aria-label="活动录音">
              <button className="recording-return" onClick={() => navigate('current')}>
                <span className="recording-dot" />
                <strong>{interruptedConnection ? '录制中断' : labels[recording.state]}</strong>
                <span className="recording-time" aria-label="录音时长">
                  {duration(recording.elapsedMs)}
                </span>
                <span>返回当前会议</span>
              </button>
              {recordingControls}
            </section>
          )}
        </main>
      </div>
      {commandOpen && <CommandPalette commands={commands} onClose={() => setCommandOpen(false)} />}
    </div>
  )
}
