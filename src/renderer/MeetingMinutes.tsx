import { useEffect, useRef, useState } from 'react'
import type { SummarySource, SummaryView } from '../shared/summary-contracts'
import { time } from './Transcription'
const labels = {
  queued: '等待生成',
  running: '正在生成纪要',
  completed: '纪要已完成',
  failed: '生成失败',
  interrupted: '生成已中断',
}
export function MeetingMinutes({
  meetingId,
  playable,
  onSeek,
}: {
  meetingId: string
  playable: boolean
  onSeek: (ms: number) => void
}): React.JSX.Element {
  const [view, setView] = useState<SummaryView | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [source, setSource] = useState<SummarySource | null>(null)
  const quote = useRef<HTMLDivElement>(null)
  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    async function poll(): Promise<void> {
      try {
        const response = await window.paa.getSummary(meetingId)
        if (!alive) return
        if (response.ok) setView(response.value)
        else setError(response.message)
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
  }, [meetingId])
  useEffect(() => {
    quote.current?.scrollIntoView({ block: 'nearest' })
  }, [source])
  async function generate(): Promise<void> {
    setBusy(true)
    setError('')
    try {
      const response = await window.paa.generateSummary(meetingId)
      if (response.ok) setView(response.value)
      else setError(response.message)
    } catch {
      setError('生成请求未确认，请查看当前状态后再操作。')
    } finally {
      setBusy(false)
    }
  }
  async function showSource(id: string): Promise<void> {
    const response = await window.paa.getSummarySource(meetingId, id)
    if (response.ok) setSource(response.value)
    else setError(response.message)
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
  const content = view?.result?.content
  const active = view?.task && ['queued', 'running'].includes(view.task.state)
  return (
    <section className="minutes-card" aria-label="会议纪要">
      <div className="section-heading">
        <h2>会议纪要</h2>
        <span role="status">{view?.task ? labels[view.task.state] : '尚未生成'}</span>
      </div>
      {!content && !active && <p>转写完成后，即可整理这场会议的要点与待办。</p>}
      {(error || view?.task?.error) && (
        <p role="alert" className="audio-warning">
          {error || view?.task?.error}
        </p>
      )}
      <button
        className="secondary-button"
        disabled={!!active || busy}
        onClick={() => void generate()}
      >
        {active ? '生成中…' : content ? '重新生成纪要' : '生成纪要'}
      </button>
      {view?.result && content && (
        <article className="minutes-content">
          <h3>{content.title}</h3>
          <small>
            {view.result.serviceName} · {view.result.model} ·{' '}
            {new Date(view.result.generatedAt).toLocaleString()}
          </small>
          {view.result.sourceIncomplete && (
            <p className="audio-warning">录音曾中断，本纪要仅依据保留下来的内容。</p>
          )}
          {view.task?.state !== 'completed' && <p>以下为上一次成功保存的纪要。</p>}
          <p className="minutes-abstract">{content.abstract}</p>
          <h4>讨论要点</h4>
          {content.topics.length ? (
            <ul>
              {content.topics.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          ) : (
            <p>未提及</p>
          )}
          <h4>明确决策</h4>
          {content.decisions.length ? (
            <ul>
              {content.decisions.map((item, index) => (
                <li key={index}>
                  {item.text}
                  {refs(item.sources)}
                </li>
              ))}
            </ul>
          ) : (
            <p>未形成明确决策</p>
          )}
          <h4>行动项</h4>
          {content.actions.length ? (
            <ul className="minutes-actions">
              {content.actions.map((item, index) => (
                <li key={index}>
                  <strong>{item.task}</strong>
                  <p>
                    负责人：{item.owner ?? '待确认'} · 截止：{item.deadline ?? '待确认'} · 状态：
                    {item.status ?? '待确认'}
                  </p>
                  {refs(item.sources)}
                </li>
              ))}
            </ul>
          ) : (
            <p>未明确行动项</p>
          )}
          <h4>风险</h4>
          {content.risks.length ? (
            <ul>
              {content.risks.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          ) : (
            <p>未提及</p>
          )}
          <h4>待确认问题</h4>
          {content.openQuestions.length ? (
            <ul>
              {content.openQuestions.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          ) : (
            <p>未提及</p>
          )}
        </article>
      )}
      {source && (
        <div ref={quote} className="source-quote" aria-label="纪要引用原文">
          <div className="section-heading">
            <strong>原文 · {time(source.startMs)}</strong>
            <button className="text-button" onClick={() => setSource(null)}>
              收起原文
            </button>
          </div>
          <blockquote>{source.text}</blockquote>
          <button
            className="secondary-button"
            disabled={!playable}
            onClick={() => onSeek(source.startMs)}
          >
            播放此处录音
          </button>
        </div>
      )}
    </section>
  )
}
