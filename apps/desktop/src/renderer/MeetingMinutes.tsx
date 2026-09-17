import type { MeetingHit } from '../shared/library-contracts'
import { useEffect, useRef, useState } from 'react'
import type { SummaryInputMode, SummarySource, SummaryView } from '../shared/summary-contracts'
import { time } from './Transcription'
import { MinutesAnalysis } from './MinutesAnalysis'
const labels = {
  waiting_speakers: '等待发言人处理',
  queued: '等待生成',
  running: '正在生成纪要',
  completed: '纪要已完成',
  failed: '生成失败',
  interrupted: '生成已中断',
}
export function MeetingMinutes({
  meetingId,
  hit,
  onSummaryAvailable,
  playable,
  onSeek,
  onTranscript,
  onServices,
  connected,
  visible,
}: {
  meetingId: string
  hit?: Extract<MeetingHit, { source: 'summary' }> | null
  onSummaryAvailable?: (value: boolean) => void
  playable: boolean
  onSeek: (ms: number) => void
  onTranscript: (id?: string) => void
  onServices: () => void
  connected: boolean
  visible: boolean
}): React.JSX.Element {
  const [inputMode, setInputMode] = useState<SummaryInputMode>('speakers')
  const [view, setView] = useState<SummaryView | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [source, setSource] = useState<SummarySource | null>(null)
  const article = useRef<HTMLElement>(null)
  const locatedHit = useRef(false)
  const quote = useRef<HTMLDivElement>(null)
  const sourceRequest = useRef(0)
  const resultVersion = useRef<string | null>(null)
  const sourceTrigger = useRef<HTMLElement | null>(null)
  const [configured, setConfigured] = useState<boolean | null>(null)
  useEffect(() => {
    if (!visible) return
    let alive = true
    void window.paa
      .listModelServices()
      .then((result) => {
        if (alive && result.ok) setConfigured(!!result.value.activeProfileId)
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [visible])
  useEffect(() => {
    if (!connected) return
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    async function poll(): Promise<void> {
      try {
        const response = await window.paa.getSummary(meetingId)
        if (!alive) return
        if (response.ok) {
          setView(response.value)
          const generatedAt = response.value.result?.generatedAt ?? null
          if (resultVersion.current !== generatedAt) {
            resultVersion.current = generatedAt
            setSource(null)
            sourceRequest.current++
          }
          onSummaryAvailable?.(!!response.value.result)
        } else setError(response.message)
      } catch {
        if (alive) setError('无法读取纪要，请重新连接。')
      } finally {
        if (alive) timer = setTimeout(() => void poll(), 1000)
      }
    }
    void poll()
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [meetingId, connected, onSummaryAvailable])
  useEffect(() => {
    if (source && visible) quote.current?.focus()
  }, [source, visible])
  useEffect(() => {
    if (!hit || !view?.result || !visible || locatedHit.current) return
    locatedHit.current = true
    if (view.result.generatedAt !== hit.generatedAt) return
    const element = article.current?.querySelector<HTMLElement>(
      `[data-summary-location="${hit.locator}"]`,
    )
    if (element) {
      element.classList.add('source-target')
      element.tabIndex = -1
      element.focus()
      element.scrollIntoView({ block: 'center' })
    }
  }, [hit, view, visible])
  async function generate(): Promise<void> {
    setBusy(true)
    setError('')
    try {
      const response = await window.paa.generateSummary(meetingId, inputMode)
      if (response.ok) setView(response.value)
      else setError(response.message)
    } catch {
      setError('生成请求未确认，请查看当前状态后再操作。')
    } finally {
      setBusy(false)
    }
  }
  async function showSource(id: string): Promise<void> {
    const current = ++sourceRequest.current
    sourceTrigger.current = document.activeElement as HTMLElement
    try {
      const response = await window.paa.getSummarySource(meetingId, id)
      if (sourceRequest.current !== current) return
      if (response.ok) setSource(response.value)
      else setError(response.message)
    } catch {
      if (sourceRequest.current === current) setError('无法读取引用原文，请重试。')
    }
  }
  const refs = (ids: string[]): React.JSX.Element => (
    <span className="source-links">
      {ids.map((id, index) => (
        <button className="text-button" key={id} onClick={() => void showSource(id)}>
          原文 {index + 1}
        </button>
      ))}
    </span>
  )
  function closeSource(): void {
    setSource(null)
    sourceRequest.current++
    sourceTrigger.current?.focus()
  }
  const content = view?.result?.content
  const active = view?.task && ['waiting_speakers', 'queued', 'running'].includes(view.task.state)
  return (
    <section className="minutes-card" aria-label="会议纪要">
      <div className="section-heading">
        <h2>会议纪要</h2>
        <div className="minutes-heading-actions">
          <span role="status">{view?.task ? labels[view.task.state] : '尚未生成'}</span>
          <button
            className="secondary-button"
            disabled={!!active || busy || !connected || configured === false}
            onClick={() => void generate()}
          >
            {view?.task?.state === 'waiting_speakers'
              ? '等待发言人…'
              : active
                ? '生成中…'
                : content
                  ? '重新生成纪要'
                  : '生成纪要'}
          </button>
        </div>
      </div>
      <div className="minutes-input-options">
        <label>
          生成依据
          <select
            value={inputMode}
            onChange={(event) => setInputMode(event.target.value as SummaryInputMode)}
            disabled={!!active || busy}
          >
            <option value="speakers">含发言人信息</option>
            <option value="text">仅文字</option>
          </select>
        </label>
        <small>
          {inputMode === 'speakers'
            ? '姓名和对应文字将发送给已配置的纪要服务。'
            : '仅发送文字记录；原话中的姓名会保留。'}
        </small>
      </div>
      {!content && !active && (
        <div className="minutes-empty">
          <p>
            {configured === false
              ? '尚未选择纪要模型服务。配置服务后，可根据完整文字生成纪要。'
              : '转写完成后，即可整理这场会议的要点与待办。'}
          </p>
          <div className="button-row">
            <button className="text-button" onClick={() => onTranscript()}>
              查看文字记录
            </button>
            {configured === false && (
              <button className="text-button" onClick={onServices}>
                配置模型服务
              </button>
            )}
          </div>
        </div>
      )}
      {hit && view?.result && hit.generatedAt !== view.result.generatedAt && (
        <p role="status" className="audio-warning">
          纪要已更新，请返回列表刷新搜索后重新定位。
        </p>
      )}
      {(error || view?.task?.error) && (
        <p role="alert" className="audio-warning">
          {error || view?.task?.error}
        </p>
      )}
      <div className={`minutes-layout ${source ? 'with-source' : ''}`}>
        {view?.result && content && (
          <article ref={article} className="minutes-content">
            <h3 data-summary-location="title">{content.title}</h3>
            <small>
              {view.result.serviceName} · {view.result.model} ·{' '}
              {new Date(view.result.generatedAt).toLocaleString()} ·{' '}
              {view.result.inputMode === 'speakers' ? '含发言人信息' : '仅文字'}
            </small>
            {view.result.stale && (
              <p className="audio-warning" role="status">
                会议资料已更新，纪要待更新。此纪要保留生成时的内容与引用。
              </p>
            )}
            {view.result.speakerIncomplete && (
              <p className="audio-warning">发言人信息不完整，本纪要依据生成时已有资料整理。</p>
            )}
            {view.result.sourceIncomplete && (
              <p className="audio-warning">录音曾中断，本纪要仅依据保留下来的内容。</p>
            )}
            {view.task?.state !== 'completed' && <p>以下为上一次成功保存的纪要。</p>}
            <MinutesAnalysis content={content} references={refs} />
          </article>
        )}
        {source && (
          <div
            ref={quote}
            tabIndex={-1}
            className="source-quote"
            aria-label="纪要引用原文"
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                event.preventDefault()
                closeSource()
              }
            }}
          >
            <div className="section-heading">
              <strong>原文 · {time(source.startMs)}</strong>
              <button className="text-button" onClick={closeSource}>
                收起原文
              </button>
            </div>
            <small>
              {time(source.startMs)} – {time(source.endMs)}
            </small>
            <blockquote>{source.text}</blockquote>
            <button
              className="secondary-button"
              disabled={!playable}
              onClick={() => onSeek(source.startMs)}
            >
              播放此处录音
            </button>
            {view?.result?.stale && <small>当前资料已更新，以下引用保留生成时的原文。</small>}
            <button
              className="text-button"
              disabled={!!view?.result?.stale}
              onClick={() => onTranscript(source.id)}
            >
              在完整文字中查看
            </button>
          </div>
        )}
      </div>
    </section>
  )
}
