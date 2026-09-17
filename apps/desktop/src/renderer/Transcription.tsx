import { SpeakerPanel } from './SpeakerPanel'
import type { SpeakerStatus } from '../shared/speaker-contracts'
export { ModelSettings } from './LocalModelSettings'
import { languageNames } from './LocalModelSettings'
import { useEffect, useRef, useState } from 'react'
import type {
  ModelState,
  TranscriptionLanguage,
  TranscriptionStatus,
  TranscriptSegment,
} from '../shared/contracts'

export const time = (milliseconds: number): string => {
  const seconds = Math.floor(milliseconds / 1000)
  return `${Math.floor(seconds / 60)
    .toString()
    .padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`
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
  onModels,
}: {
  meetingId: string
  modelReady: boolean
  playable: boolean
  onSeek?: (ms: number) => void
  visible?: boolean
  live?: boolean
  connected?: boolean
  target?: { id: string; request: number } | null
  onModels: () => void
}): React.JSX.Element {
  const [rerunModel, setRerunModel] = useState<ModelState | null>(null)
  const [rerunOpen, setRerunOpen] = useState(false)
  const [selectedModel, setSelectedModel] = useState('small')
  const [selectedLanguage, setSelectedLanguage] = useState<TranscriptionLanguage>('zh')
  const [summaryBusy, setSummaryBusy] = useState(false)
  const rerunDialog = useRef<HTMLDialogElement>(null)
  const rerunTrigger = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (rerunOpen) rerunDialog.current?.showModal()
  }, [rerunOpen])
  const [speakerState, setSpeakerState] = useState<SpeakerStatus | null>(null)
  const [speakerSegment, setSpeakerSegment] = useState<TranscriptSegment | null>(null)
  const speakerVersion = useRef('')
  const publication = useRef<string | undefined>(undefined)
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
        let speakersChanged = false
        let nextSpeakerVersion = speakerVersion.current
        if (!state.value.candidate) {
          const speakers = await window.paa.speakers({ action: 'status', meetingId })
          if (!alive) return
          if (speakers.ok && 'speakers' in speakers.value) {
            const next = speakers.value
            setSpeakerState(next)
            const version = `${next.generation}:${next.revision}:${next.state}`
            if (speakerVersion.current !== version) {
              nextSpeakerVersion = version
              speakersChanged = true
            }
          }
        } else setSpeakerState(null)
        if (publication.current !== state.value.publication) {
          publication.current = state.value.publication
          cursor.current = -1
          loaded.current = []
          more.current = true
          explicitLoad = true
          setSegments([])
        }
        const looking = !!target && !loaded.current.some((segment) => segment.id === target.id)
        if (looking) setLocating(true)
        // A citation can reference any page. Consume sequential cursors until found,
        // while ordinary historical reading fetches only an explicitly requested page.
        if (explicitLoad || looking || live || !more.current || speakersChanged) {
          const refreshThrough = speakersChanged ? cursor.current : -1
          let nextCursor = speakersChanged ? -1 : cursor.current
          let updated = speakersChanged ? ([] as TranscriptSegment[]) : loaded.current
          do {
            const page = await window.paa.listTranscript(meetingId, nextCursor, publication.current)
            if (!alive) return
            if (!page.ok) {
              if (page.code === 'transcript_changed') {
                publication.current = undefined
                return
              }
              setError(page.message)
              return
            }
            const next = page.value
            if (next.hasMore && next.nextCursor <= nextCursor)
              throw new Error('文字分页未前进，请重试。')
            nextCursor = next.nextCursor
            more.current = next.hasMore
            const ids = new Set(updated.map((segment) => segment.id))
            updated = [...updated, ...next.segments.filter((segment) => !ids.has(segment.id))]
          } while (
            more.current &&
            (nextCursor < refreshThrough ||
              (target && !updated.some((segment) => segment.id === target.id)))
          )
          cursor.current = nextCursor
          loaded.current = updated
          setSegments(updated)
          setHasMore(more.current)
          speakerVersion.current = nextSpeakerVersion
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
  async function openRerun(): Promise<void> {
    setBusy(true)
    setError('')
    try {
      const [models, summary] = await Promise.all([
        window.paa.getTranscriptionModel(),
        window.paa.getSummary(meetingId),
      ])
      if (!models.ok) {
        setError(models.message)
        return
      }
      if (!summary.ok) {
        setError(summary.message)
        return
      }
      setRerunModel(models.value)
      setSelectedModel(models.value.defaultModel)
      setSelectedLanguage(models.value.language)
      setSummaryBusy(
        !!summary.value.task && ['queued', 'running'].includes(summary.value.task.state),
      )
      setRerunOpen(true)
    } catch {
      setError('无法读取转写设置，请稍后重试。')
    } finally {
      setBusy(false)
    }
  }
  function closeRerun(): void {
    rerunDialog.current?.close()
    setRerunOpen(false)
    rerunTrigger.current?.focus()
  }
  async function rerun(cancel = false): Promise<void> {
    setBusy(true)
    setError('')
    try {
      const result = await (cancel
        ? window.paa.cancelRetranscription(meetingId)
        : window.paa.rerunTranscription(meetingId, selectedModel, selectedLanguage))
      if (result.ok) {
        setStatus(result.value)
        if (!cancel) closeRerun()
      } else setError(result.message)
    } catch {
      setError('请求未确认，请查看转写状态后重试。')
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
          {locating
            ? '正在定位引用…'
            : status
              ? `${status.candidate ? '重新转写 · ' : ''}${states[status.state]}`
              : '正在读取文字'}
        </span>
      </div>
      {status?.published && (
        <p className="transcript-configuration">
          当前文字：
          {status.published.modelId
            .split('/')
            .at(-1)
            ?.replace(/^(?:faster-)?whisper-/, 'Whisper ')
            .replace(/-mlx$/, '')}{' '}
          · {languageNames[status.published.language]}
          {' · '}
          {(status.published.device ?? 'cpu').toUpperCase()}
        </p>
      )}
      {status?.actual && (!status.published || status.candidate) && (
        <p className="transcript-configuration">
          {status.candidate ? '本次重新转写' : '本次转写'}：
          {status.actual.modelId
            .split('/')
            .at(-1)
            ?.replace(/^(?:faster-)?whisper-/, 'Whisper ')
            .replace(/-mlx$/, '')}{' '}
          · {languageNames[status.actual.language]}
          {' · '}
          {(status.actual.device ?? 'cpu').toUpperCase()}
        </p>
      )}
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
      {(!live || (speakerState && speakerState.state !== 'not_started')) && (
        <SpeakerPanel
          key={speakerSegment?.id ?? 'toolbar'}
          status={speakerState}
          segment={speakerSegment}
          onCloseSegment={() => setSpeakerSegment(null)}
          connected={connected}
          live={live}
        />
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
            <div className="speaker-transcript-row" key={segment.id}>
              {speakerState && speakerState.state !== 'not_started' && (
                <button
                  className="speaker-label"
                  title="调整这段发言的说话人"
                  onClick={() => setSpeakerSegment(segment)}
                  disabled={!connected}
                >
                  {segment.speakerName || '多人／待确认'}
                </button>
              )}
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
            </div>
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
            disabled={!(status?.canContinue ?? modelReady) || busy || !connected}
            onClick={() => void start()}
          >
            {busy ? '正在请求…' : status.state === 'not_started' ? '生成转写' : '继续转写'}
          </button>
        )}
        {!live &&
          playable &&
          status &&
          !['queued', 'running', 'draining', 'not_started'].includes(status.state) && (
            <button
              ref={rerunTrigger}
              className="secondary-button"
              disabled={busy || !connected}
              onClick={() => void openRerun()}
            >
              重新转写
            </button>
          )}
        {status?.candidate && (
          <button
            className="text-button"
            disabled={busy || !connected}
            onClick={() => void rerun(true)}
          >
            取消重新转写
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
      {rerunOpen && (
        <dialog
          ref={rerunDialog}
          className="library-dialog"
          onCancel={(event) => {
            event.preventDefault()
            if (!busy) closeRerun()
          }}
        >
          <h2>重新转写这场会议</h2>
          <p>成功后替换当前文字。原纪要将保留并标记待更新，由你手动重新生成。</p>
          <label>
            转写模型
            <select
              value={selectedModel}
              onChange={(event) => setSelectedModel(event.target.value)}
              disabled={busy}
            >
              {rerunModel?.models.map((item) => (
                <option value={item.id} key={item.id} disabled={item.state !== 'ready'}>
                  {item.name}
                  {item.state !== 'ready' ? '（未就绪）' : ''}
                </option>
              ))}
            </select>
          </label>
          <label>
            识别语言
            <select
              value={selectedLanguage}
              onChange={(event) => setSelectedLanguage(event.target.value as TranscriptionLanguage)}
              disabled={busy}
            >
              {Object.entries(languageNames).map(([value, name]) => (
                <option key={value} value={value}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          {summaryBusy && <p className="audio-warning">纪要正在生成，请完成后重试。</p>}
          {error && (
            <p role="alert" className="audio-warning">
              {error}
            </p>
          )}
          <div className="button-row">
            <button className="secondary-button" disabled={busy} onClick={closeRerun}>
              取消
            </button>
            <button
              className="primary-button"
              disabled={
                busy ||
                summaryBusy ||
                rerunModel?.models.find((item) => item.id === selectedModel)?.state !== 'ready'
              }
              onClick={() => void rerun()}
            >
              确认重新转写
            </button>
          </div>
        </dialog>
      )}
      {canStart && status.continuationBlockedReason && (
        <p className="audio-warning" role="status">
          {status.continuationBlockedReason}{' '}
          <button className="text-button" onClick={onModels}>
            查看本地转写模型
          </button>
        </p>
      )}
    </section>
  )
}
