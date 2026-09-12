import { useEffect, useRef, useState } from 'react'
import { AudioLines, Search, X } from 'lucide-react'
import type { Meeting } from '../shared/contracts'
import type { LibraryPage, MeetingHit } from '../shared/library-contracts'
import { MeetingActions } from './MeetingActions'
import { MeetingProcessingState } from './MeetingProcessingState'
import { audioTime } from './AudioPlayer'
import { highlightedParts, meetingQuery, QueryGeneration } from './meeting-library-query'
export function Highlight({ text, query }: { text: string; query: string }): React.JSX.Element {
  return (
    <>
      {highlightedParts(text, query).map((part, index) =>
        part.hit ? <mark key={index}>{part.text}</mark> : <span key={index}>{part.text}</span>,
      )}
    </>
  )
}
export function MeetingLibraryList({
  connected,
  visible,
  refreshVersion,
  onOpen,
  onChanged,
  onDeleted,
}: {
  connected: boolean
  visible: boolean
  refreshVersion: number
  onOpen: (id: string, hit?: MeetingHit | null) => void
  onChanged: (meeting: Meeting) => void
  onDeleted: (id: string) => void
}): React.JSX.Element {
  const [text, setText] = useState(''),
    [from, setFrom] = useState(''),
    [to, setTo] = useState('')
  const [datesEdited, setDatesEdited] = useState(false),
    [dateReset, setDateReset] = useState(0)
  const [items, setItems] = useState<LibraryPage['items']>([])
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [loaded, setLoaded] = useState(false)
  const [more, setMore] = useState(false),
    [composing, setComposing] = useState(false),
    [refresh, setRefresh] = useState(0)
  const generation = useRef(new QueryGeneration())
  useEffect(() => {
    const controller = generation.current
    const version = controller.next()
    if (!connected || composing) return
    const timer = setTimeout(() => {
      void load(0, version)
    }, 250)
    return () => {
      clearTimeout(timer)
      controller.next()
    }
    async function load(offset: number, version: number): Promise<void> {
      setBusy(true)
      setError('')
      try {
        const query = meetingQuery(text, from, to, offset)
        const result = await window.paa.queryMeetings(query)
        if (!generation.current.current(version)) return
        if (!result.ok) throw new Error(result.message)
        generation.current.apply(version, query)
        setItems(result.value.items)
        setMore(result.value.hasMore)
        setLoaded(true)
      } catch (cause) {
        if (generation.current.current(version))
          setError(cause instanceof Error ? cause.message : '搜索失败，请重试。')
      } finally {
        if (generation.current.current(version)) setBusy(false)
      }
    }
  }, [text, from, to, connected, composing, refresh, refreshVersion])
  async function next(): Promise<void> {
    const request = generation.current.page(items.length)
    if (!request) return
    const { version, query } = request
    setBusy(true)
    setError('')
    try {
      const result = await window.paa.queryMeetings(query)
      if (!generation.current.current(version)) return
      if (!result.ok) throw new Error(result.message)
      setItems((previous) => [
        ...previous,
        ...result.value.items.filter(
          (item) => !previous.some((old) => old.meeting.id === item.meeting.id),
        ),
      ])
      setMore(result.value.hasMore)
    } catch (cause) {
      if (generation.current.current(version))
        setError(cause instanceof Error ? cause.message : '加载失败，请重试。')
    } finally {
      generation.current.finish(version)
      if (generation.current.current(version)) setBusy(false)
    }
  }
  function invalidateQuery(): void {
    generation.current.next()
    setMore(false)
    setBusy(false)
  }
  function invalidate(): void {
    invalidateQuery()
    setRefresh((value) => value + 1)
  }
  return (
    <section className="meetings-section" aria-labelledby="meetings-title">
      <div className="section-heading">
        <h2 id="meetings-title">
          我的会议 <span>{loaded ? items.length : '—'}</span>
        </h2>
        <button className="text-button" disabled={!connected || busy} onClick={invalidate}>
          刷新记录
        </button>
      </div>
      <div className="library-filters">
        <label className="library-search">
          <Search size={18} />
          <input
            aria-label="搜索会议"
            placeholder="搜索名称、文字记录和纪要"
            value={text}
            maxLength={200}
            onCompositionStart={() => {
              invalidateQuery()
              setComposing(true)
            }}
            onCompositionEnd={(event) => {
              invalidateQuery()
              setText(event.currentTarget.value)
              setComposing(false)
            }}
            onChange={(event) => {
              invalidateQuery()
              setText(event.target.value)
            }}
          />
        </label>
        <label>
          开始日期
          <input
            key={`from-${dateReset}`}
            type="date"
            value={from}
            onInput={() => setDatesEdited(true)}
            onChange={(event) => {
              invalidateQuery()
              setFrom(event.target.value)
            }}
          />
        </label>
        <label>
          结束日期
          <input
            key={`to-${dateReset}`}
            type="date"
            value={to}
            onInput={() => setDatesEdited(true)}
            onChange={(event) => {
              invalidateQuery()
              setTo(event.target.value)
            }}
          />
        </label>
        {(text || from || to || datesEdited) && (
          <button
            className="text-button"
            onClick={() => {
              invalidate()
              setText('')
              setFrom('')
              setTo('')
              setDatesEdited(false)
              setDateReset((value) => value + 1)
            }}
          >
            <X size={15} />
            清除
          </button>
        )}
      </div>
      {busy && <p role="status">正在查找会议…</p>}
      {error && (
        <p role="alert" className="audio-warning">
          {error}{' '}
          <button className="text-button" onClick={invalidate}>
            重试
          </button>
        </p>
      )}
      <div className="meeting-list">
        {items.map(({ meeting, hit }) => (
          <div className="library-row" key={meeting.id}>
            <button className="meeting-row" onClick={() => onOpen(meeting.id)}>
              <span className="row-icon">
                <AudioLines size={21} />
              </span>
              <span className="row-title">
                <strong>
                  <Highlight text={meeting.title} query={text.trim()} />
                </strong>
                <small>
                  {new Date(meeting.startedAt || meeting.createdAt).toLocaleString('zh-CN', {
                    hour12: false,
                  })}
                </small>
              </span>
              <span>{audioTime(meeting.durationMs / 1000)}</span>
              <span className="row-state">
                <span className={`meeting-state ${meeting.status}`}>
                  {meeting.deleting
                    ? '删除未完成'
                    : meeting.status === 'completed'
                      ? '已完成'
                      : meeting.status === 'interrupted'
                        ? '录制中断'
                        : meeting.status === 'failed'
                          ? '录制失败'
                          : '录音中'}
                </span>
                {!meeting.deleting && (
                  <MeetingProcessingState
                    meetingId={meeting.id}
                    state={meeting.status}
                    connected={connected}
                    visible={visible}
                    refreshVersion={refreshVersion}
                  />
                )}
              </span>
            </button>
            <MeetingActions
              meeting={meeting}
              visible={visible}
              onChanged={(updated) => {
                onChanged(updated)
                invalidate()
              }}
              onDeleted={(id) => {
                onDeleted(id)
                invalidate()
              }}
            />
            {hit && (
              <button className="search-hit" onClick={() => onOpen(meeting.id, hit)}>
                <small>
                  {hit.source === 'transcript'
                    ? `文字记录 · ${audioTime(hit.startMs / 1000)}`
                    : hit.source === 'summary'
                      ? '会议纪要'
                      : '会议名称'}
                </small>
                <span>
                  <Highlight text={hit.text} query={text.trim()} />
                </span>
              </button>
            )}
            {meeting.deletionError && <p className="audio-warning">{meeting.deletionError}</p>}
          </div>
        ))}
      </div>
      {!busy && !error && !items.length && (
        <div className="empty-state">
          <AudioLines size={38} />
          <h3>
            {text || from || to
              ? '没有找到匹配的会议'
              : loaded
                ? '暂无会议记录'
                : '正在加载会议记录'}
          </h3>
          <p>
            {text || from || to ? '试试其他关键词或日期范围。' : '开始录音后，可在这里查看会议。'}
          </p>
        </div>
      )}
      {more && (
        <button className="text-button" disabled={busy || !connected} onClick={() => void next()}>
          加载更多
        </button>
      )}
    </section>
  )
}
