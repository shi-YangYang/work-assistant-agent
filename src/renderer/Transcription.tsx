import { CollapsibleSection } from './CollapsibleSection'
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
      <div className="section-heading">
        <h2>Whisper small</h2>
        <span className="status-badge">
          {model?.state === 'ready' ? '本地转写已就绪' : '准备本地转写'}
        </span>
      </div>
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
      <CollapsibleSection
        id="model-information"
        title="模型信息"
        summary="Whisper small · 多语言 · CPU INT8"
      >
        <p>Whisper small 多语言</p>
        <p>来源：{model?.source ?? 'Hugging Face · SYSTRAN'} · MIT 许可</p>
      </CollapsibleSection>
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
  visible = true,
  live = false,
  connected = true,
  target,
}: {
  meetingId: string
  modelReady: boolean
  playable: boolean
  onSeek?: (ms: number) => void
  visible?: boolean
  live?: boolean
  connected?: boolean
  target?: { id: string; request: number } | null
}): React.JSX.Element {
  const [status, setStatus] = useState<TranscriptionStatus | null>(null)
  const [segments, setSegments] = useState<TranscriptSegment[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const [loadRequest, setLoadRequest] = useState(0)
  const [locating, setLocating] = useState(false)
  const viewport = useRef<HTMLDivElement>(null)
  const cursor = useRef(-1)
  const loaded = useRef<TranscriptSegment[]>([])
  const more = useRef(true)
  const follow = useRef(live)
  const located = useRef<number | null>(null)
  useEffect(() => {
    if (!connected) return
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    let explicitLoad = true
    async function poll(): Promise<void> {
      try {
        const state = await window.paa.getTranscriptionStatus(meetingId)
        if (!alive) return
        if (!state.ok) {
          setError(state.message)
          return
        }
        setStatus(state.value)
        const looking = !!target && !loaded.current.some((segment) => segment.id === target.id)
        if (looking) setLocating(true)
        // A citation can reference any page. Consume sequential cursors until found,
        // while ordinary historical reading fetches only an explicitly requested page.
        if (explicitLoad || looking || live || !more.current) {
          do {
            const page = await window.paa.listTranscript(meetingId, cursor.current)
            if (!alive) return
            if (!page.ok) {
              setError(page.message)
              return
            }
            const next = page.value
            if (next.hasMore && next.nextCursor <= cursor.current)
              throw new Error('文字分页未前进，请重试。')
            cursor.current = next.nextCursor
            more.current = next.hasMore
            const ids = new Set(loaded.current.map((segment) => segment.id))
            loaded.current = [
              ...loaded.current,
              ...next.segments.filter((segment) => !ids.has(segment.id)),
            ]
            setSegments(loaded.current)
            setHasMore(next.hasMore)
          } while (
            target &&
            !loaded.current.some((segment) => segment.id === target.id) &&
            more.current
          )
          explicitLoad = false
        }
        setError(
          looking && !more.current && !loaded.current.some((segment) => segment.id === target?.id)
            ? '当前文字中未找到该引用片段，请返回纪要重试。'
            : '',
        )
      } catch (failure) {
        if (alive)
          setError(failure instanceof Error ? failure.message : '无法读取文字，请重新连接。')
      } finally {
        if (alive) {
          setLocating(false)
          timer = setTimeout(() => void poll(), 800)
        }
      }
    }
    void poll()
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [meetingId, connected, target, loadRequest, live])
  useEffect(() => {
    if (!visible || !viewport.current) return
    if (target && located.current !== target.request) {
      const line = Array.from(
        viewport.current.querySelectorAll<HTMLButtonElement>('[data-segment-id]'),
      ).find((element) => element.dataset.segmentId === target.id)
      if (line) {
        follow.current = false
        located.current = target.request
        viewport.current.scrollTop +=
          line.getBoundingClientRect().top - viewport.current.getBoundingClientRect().top - 24
        line.focus({ preventScroll: true })
      }
    } else if (follow.current) viewport.current.scrollTop = viewport.current.scrollHeight
  }, [segments, target, visible])
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
        <h2>{live ? '实时文字' : '会议文字'}</h2>
        <span role="status">
          {locating ? '正在定位引用…' : status ? states[status.state] : '正在读取文字'}
        </span>
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
            follow.current =
              live && element.scrollHeight - element.scrollTop - element.clientHeight < 40
        }}
      >
        {segments.length ? (
          segments.map((segment) => (
            <button
              className={`transcript-line ${segment.id === target?.id ? 'source-target' : ''}`}
              key={segment.id}
              data-segment-id={segment.id}
              aria-disabled={!playable}
              onClick={() => {
                if (playable) onSeek?.(segment.startMs)
              }}
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
      <div className="transcript-actions">
        {canStart && (
          <button
            className="secondary-button"
            disabled={!modelReady || busy || !connected}
            onClick={() => void start()}
          >
            {busy ? '正在请求…' : status.state === 'not_started' ? '生成转写' : '继续转写'}
          </button>
        )}
        {hasMore && (
          <button
            className="text-button"
            disabled={locating || !connected}
            onClick={() => setLoadRequest((value) => value + 1)}
          >
            加载后续文字
          </button>
        )}
        {live && segments.length > 0 && (
          <button
            className="text-button"
            onClick={() => {
              follow.current = true
              if (viewport.current) viewport.current.scrollTop = viewport.current.scrollHeight
            }}
          >
            回到最新内容
          </button>
        )}
        {!playable && <small>回放暂不可用。</small>}
      </div>
      {!modelReady && <p>在本地转写模型页下载模型后即可使用，录音不受影响。</p>}
    </section>
  )
}
