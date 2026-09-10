import { useEffect, useRef, useState } from 'react'
import type { ModelState, TranscriptionStatus, TranscriptSegment } from '../shared/contracts'

export const time = (milliseconds: number): string => {
  const seconds = Math.floor(milliseconds / 1000)
  return `${Math.floor(seconds / 60)
    .toString()
    .padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`
}
export function ModelSettings({
  model,
  refresh,
}: {
  model: ModelState | null
  refresh: () => void
}): React.JSX.Element {
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const preparing = model?.state === 'downloading' || model?.state === 'verifying'
  async function act(cancel = false): Promise<void> {
    setBusy(true)
    setError('')
    try {
      const result = await (cancel
        ? window.paa.cancelModelDownload()
        : window.paa.downloadTranscriptionModel())
      if (!result.ok) setError(result.message)
      refresh()
    } catch {
      setError('无法确认模型状态，请稍后重试。')
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="settings-card model-card" aria-label="本地转写模型">
      <h2>本地转写模型</h2>
      <p>支持中文及中英混合转写。</p>
      <p>下载约 {model ? Math.ceil(model.totalBytes / 1e6) : 487} MB，请预留 1.1 GB 磁盘空间。</p>
      <p>下载需要联网，完成后可离线转写。</p>
      <strong role="status">
        {model?.state === 'ready'
          ? '模型已就绪'
          : model?.state === 'downloading'
            ? '正在下载模型'
            : model?.state === 'verifying'
              ? '正在准备模型'
              : model?.state === 'error'
                ? '模型准备失败'
                : '模型尚未准备'}
      </strong>
      {preparing && (
        <div className="model-progress">
          <progress
            aria-label="模型下载进度"
            max={model?.totalBytes}
            value={model?.downloadedBytes}
          />
          <span>
            {Math.floor((model?.downloadedBytes ?? 0) / 1e6)} /{' '}
            {Math.ceil((model?.totalBytes ?? 1) / 1e6)} MB
          </span>
        </div>
      )}
      {(error || model?.error) && (
        <p role="alert" className="audio-warning">
          {error || model?.error}
        </p>
      )}
      {model?.state !== 'ready' && (
        <button
          className="secondary-button"
          disabled={!model || busy}
          onClick={() => void act(preparing)}
        >
          {preparing ? '取消准备' : model?.state === 'error' ? '重试下载模型' : '下载默认模型'}
        </button>
      )}
      {model?.state !== 'ready' && <p>可先录音，模型就绪后再补转写。</p>}
      <details>
        <summary>模型信息</summary>
        <p>Whisper small 多语言</p>
        <p>来源：{model?.source ?? 'Hugging Face · SYSTRAN'} · MIT 许可</p>
      </details>
    </section>
  )
}
const states: Record<TranscriptionStatus['state'], string> = {
  not_started: '尚未转写',
  queued: '等待处理',
  running: '正在转写',
  draining: '正在补齐文字',
  completed: '转写完成',
  paused: '转写已暂停',
  failed: '转写失败',
}
export function Transcript({
  meetingId,
  modelReady,
  playable,
  onSeek,
}: {
  meetingId: string
  modelReady: boolean
  playable: boolean
  onSeek?: (ms: number) => void
}): React.JSX.Element {
  const [status, setStatus] = useState<TranscriptionStatus | null>(null)
  const [segments, setSegments] = useState<TranscriptSegment[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const viewport = useRef<HTMLDivElement>(null)
  const cursor = useRef(-1)
  const follow = useRef(true)
  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    cursor.current = -1
    async function poll(): Promise<void> {
      try {
        const state = await window.paa.getTranscriptionStatus(meetingId)
        if (!alive) return
        if (!state.ok) {
          setError(state.message)
          return
        }
        setStatus(state.value)
        const page = await window.paa.listTranscript(meetingId, cursor.current)
        if (!alive) return
        if (page.ok) {
          setHasMore(page.value.hasMore)
          cursor.current = page.value.nextCursor
          if (page.value.segments.length)
            setSegments((previous) => [...previous, ...page.value.segments])
          setError('')
        } else setError(page.message)
      } catch {
        if (alive) setError('无法读取转写状态，请在设置中重新连接。')
      } finally {
        if (alive)
          timer = setTimeout(() => {
            void poll()
          }, 800)
      }
    }
    void poll()
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [meetingId])
  useEffect(() => {
    if (follow.current && viewport.current)
      viewport.current.scrollTop = viewport.current.scrollHeight
  }, [segments])
  async function start(): Promise<void> {
    setBusy(true)
    setError('')
    try {
      const result = await window.paa.startTranscription(meetingId)
      if (result.ok) setStatus(result.value)
      else setError(result.message)
    } catch {
      setError('请求未确认，正在查询已保存的转写进度。')
    } finally {
      setBusy(false)
    }
  }
  const canStart = status && ['not_started', 'paused', 'failed'].includes(status.state)
  return (
    <section className="transcript-card" aria-label="会议文字">
      <div className="section-heading">
        <h2>会议文字</h2>
        <span role="status">{status ? states[status.state] : '正在读取文字'}</span>
      </div>
      {status && (
        <p className="transcript-progress">
          已处理 {time(status.processedMs)} / 录音 {time(status.audioMs)}
          {status.pendingMs > 0 && status.state !== 'not_started'
            ? ` · 待处理 ${time(status.pendingMs)}`
            : ''}
        </p>
      )}
      {status?.sourceIncomplete && (
        <p className="audio-warning">源录音曾中断，文字仅对应保留下来的音频。</p>
      )}
      {(error || status?.error) && (
        <p role="alert" className="audio-warning">
          {error || status?.error}
        </p>
      )}
      <div
        ref={viewport}
        className="transcript-lines"
        onScroll={() => {
          const element = viewport.current
          if (element)
            follow.current = element.scrollHeight - element.scrollTop - element.clientHeight < 40
        }}
      >
        {segments.length ? (
          segments.map((segment) => (
            <button
              className="transcript-line"
              key={segment.id}
              disabled={!playable}
              onClick={() => onSeek?.(segment.startMs)}
            >
              <time>{time(segment.startMs)}</time>
              <span>{segment.text}</span>
            </button>
          ))
        ) : (
          <p className="transcript-empty">
            {status?.state === 'completed'
              ? '这段音频未检测到可识别的语音。'
              : status?.state === 'failed'
                ? '转写未完成，排除错误后可继续。'
                : status?.state === 'paused'
                  ? '已保留进度，点击继续处理。'
                  : status && ['queued', 'running', 'draining'].includes(status.state)
                    ? '正在转写，文字将分批显示。'
                    : '为这场会议生成带时间的文字记录。'}
          </p>
        )}
      </div>
      {canStart && (
        <button
          className="secondary-button"
          disabled={!modelReady || busy}
          onClick={() => void start()}
        >
          {busy ? '正在请求…' : status.state === 'not_started' ? '生成转写' : '继续转写'}
        </button>
      )}
      {!modelReady && <p>在设置中下载转写模型后即可使用，录音不受影响。</p>}
      {segments.length > 0 && (
        <button
          className="text-button"
          onClick={() => {
            follow.current = true
            if (viewport.current) viewport.current.scrollTop = viewport.current.scrollHeight
          }}
        >
          回到最新内容{hasMore ? ' · 正在加载后续文字' : ''}
        </button>
      )}
      {!playable && <small>回放暂不可用。</small>}
    </section>
  )
}
