import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { List, MessageSquare, Pencil, Plus, Search, Trash2, X } from 'lucide-react'
import type { Conversation, Page } from '@paa/api-contracts'
import type { Composer } from './audio-capture'
import { api, useResource, write } from './api'
import { ConversationChat } from './Assistant'
import { BusyButton, ErrorNotice, Modal } from './ui'
import { useWorkspace } from './workspace'
import { resumeConversation } from './assistant-session'

export function Assistant() {
  const { conversationId } = useParams()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const { drafts, setDraft, notify, lastConversationId, rememberConversation } = useWorkspace()
  const explicitNew = params.get('new') === '1'
  const showConversations = params.get('conversations') === '1'
  const [resumed, setResumed] = useState(false)
  const [resumeError, setResumeError] = useState('')
  const [resumeRevision, setResumeRevision] = useState(0)
  const newDraft = !!drafts['composer:new']
  const [search, setSearch] = useState('')
  const [pickerOpen, setPickerOpen] = useState(false)
  const expanded = pickerOpen || showConversations
  const setExpanded = useCallback(
    (open: boolean) => {
      setPickerOpen(open)
      if (!open && showConversations) {
        const next = new URLSearchParams(params)
        next.delete('conversations')
        setParams(next, { replace: true })
      }
    },
    [params, setParams, showConversations],
  )
  const picker = useRef<HTMLDivElement>(null)
  const pickerButton = useRef<HTMLButtonElement>(null)
  const closePicker = () => {
    setExpanded(false)
    pickerButton.current?.focus()
  }
  useEffect(() => {
    if (!expanded) return
    const closeOutside = (event: PointerEvent) => {
      if (!picker.current?.contains(event.target as Node)) setExpanded(false)
    }
    document.addEventListener('pointerdown', closeOutside)
    return () => document.removeEventListener('pointerdown', closeOutside)
  }, [expanded, setExpanded])
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState('')
  const [editing, setEditing] = useState<Conversation | null>(null)
  const [deleting, setDeleting] = useState<Conversation | null>(null)
  const [impact, setImpact] = useState<{ retainedSources: number } | null>(null)
  const [older, setOlder] = useState<Conversation[]>([])
  const [cursor, setCursor] = useState<string | null | undefined>()
  const [removed, setRemoved] = useState<string[]>([])
  const [renamed, setRenamed] = useState<Record<string, Conversation>>({})
  const list = useResource<Page<Conversation>>(`/conversations?q=${encodeURIComponent(search)}`)
  const current = useResource<Conversation>(
    conversationId ? `/conversations/${conversationId}` : null,
  )
  useEffect(() => {
    if (conversationId || explicitNew || newDraft) return
    let active = true
    const controller = new AbortController()
    void resumeConversation(lastConversationId, (path) => api(path, { signal: controller.signal }))
      .then((id) => {
        if (!active) return
        rememberConversation(id)
        setResumeError('')
        setResumed(true)
        if (id)
          navigate(`/assistant/${id}${showConversations ? '?conversations=1' : ''}`, {
            replace: true,
          })
      })
      .catch((error) => {
        if (active) setResumeError((error as Error).message)
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [
    conversationId,
    explicitNew,
    newDraft,
    lastConversationId,
    rememberConversation,
    navigate,
    showConversations,
    resumeRevision,
  ])
  useEffect(() => {
    if (current.data && current.data.id === conversationId) rememberConversation(current.data.id)
  }, [current.data, conversationId, rememberConversation])
  const items = [...(list.data?.items ?? []), ...older]
    .filter(
      (item, i, all) =>
        !removed.includes(item.id) && all.findIndex((row) => row.id === item.id) === i,
    )
    .map((item) => (renamed[item.id]?.revision >= item.revision ? renamed[item.id] : item))
  const nextCursor = cursor === undefined ? list.data?.nextCursor : cursor
  const updated = () => {
    list.refresh()
    current.refresh()
    window.dispatchEvent(new Event('paa-record-updated'))
  }
  const stopBeforeAction = () => {
    if (!drafts.recording) return true
    notify('请先停止录音，再管理会话；录音会保留在当前会话。')
    return false
  }
  function create() {
    if (!stopBeforeAction()) return
    setExpanded(false)
    navigate('/assistant?new=1')
    setFailure('')
  }
  return (
    <div className="assistant-workspace">
      <section className="conversation-main">
        <header className="conversation-heading">
          <h2 title={current.data?.title}>{current.data?.title ?? '工作助手'}</h2>
          <button onClick={create}>
            <Plus size={16} />
            新会话
          </button>
          <div
            ref={picker}
            className="conversation-picker"
            onBlur={(event) => {
              if (event.relatedTarget && !event.currentTarget.contains(event.relatedTarget as Node))
                setExpanded(false)
            }}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                event.preventDefault()
                event.stopPropagation()
                closePicker()
              }
            }}
          >
            <button
              ref={pickerButton}
              className="icon-button"
              aria-label="会话列表"
              aria-haspopup="dialog"
              aria-expanded={expanded}
              aria-controls="conversation-picker"
              aria-describedby={expanded ? undefined : 'conversation-picker-tip'}
              onClick={() => setExpanded(!expanded)}
            >
              <List size={20} />
            </button>
            {!expanded && (
              <span className="conversation-tooltip" role="tooltip" id="conversation-picker-tip">
                会话列表
              </span>
            )}
            {expanded && (
              <div
                className="conversation-popover"
                id="conversation-picker"
                role="dialog"
                aria-label="会话列表"
              >
                <div className="conversation-popover-heading">
                  <h2>会话</h2>
                  <button className="icon-button" aria-label="收起会话列表" onClick={closePicker}>
                    <X size={18} />
                  </button>
                </div>
                <label className="conversation-search">
                  <Search size={15} />
                  <input
                    autoFocus
                    aria-label="搜索会话"
                    placeholder="搜索会话"
                    value={search}
                    onChange={(e) => {
                      setSearch(e.target.value)
                      setOlder([])
                      setCursor(undefined)
                    }}
                  />
                </label>
                <ErrorNotice retry={list.refresh}>{list.error}</ErrorNotice>
                <div className="conversation-list">
                  {items.map((item) => (
                    <div
                      key={item.id}
                      className={`conversation-row ${item.id === conversationId ? 'active' : ''}`}
                    >
                      <Link to={`/assistant/${item.id}`} title={item.title} onClick={closePicker}>
                        <MessageSquare size={16} />
                        <span>{item.title}</span>
                      </Link>
                      <div className="conversation-row-actions">
                        <button
                          className="icon-button"
                          aria-label={`重命名会话：${item.title}`}
                          title="重命名"
                          onClick={() => {
                            if (stopBeforeAction()) {
                              closePicker()
                              setEditing(item)
                            }
                          }}
                        >
                          <Pencil size={15} />
                        </button>
                        <button
                          className="icon-button danger"
                          aria-label={`删除会话：${item.title}`}
                          title="删除会话"
                          onClick={async () => {
                            if (!stopBeforeAction()) return
                            closePicker()
                            try {
                              const latest = await api<Conversation>(`/conversations/${item.id}`)
                              const value = await api<{ retainedSources: number }>(
                                `/conversations/${item.id}/deletion`,
                              )
                              setImpact(value)
                              setDeleting(latest)
                            } catch (e) {
                              setFailure((e as Error).message)
                            }
                          }}
                        >
                          <Trash2 size={15} />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
                {nextCursor && (
                  <button
                    onClick={async () => {
                      try {
                        const next = await api<Page<Conversation>>(
                          `/conversations?q=${encodeURIComponent(search)}&cursor=${nextCursor}`,
                        )
                        setOlder((previous) => [...previous, ...next.items])
                        setCursor(next.nextCursor)
                      } catch (e) {
                        setFailure((e as Error).message)
                      }
                    }}
                  >
                    加载更多
                  </button>
                )}
                {!items.length && list.data && (
                  <p className="muted">{search ? '没有匹配的会话' : '还没有会话'}</p>
                )}
              </div>
            )}
          </div>
        </header>
        <ErrorNotice>{failure || (conversationId ? current.error : '')}</ErrorNotice>
        {!conversationId && !explicitNew && !newDraft && (
          <>
            <ErrorNotice retry={() => setResumeRevision((value) => value + 1)}>
              {resumeError}
            </ErrorNotice>
            {(!resumed || lastConversationId) && !resumeError && (
              <p className="muted">正在打开上次会话…</p>
            )}
          </>
        )}
        {(current.data ||
          (!conversationId &&
            (explicitNew || newDraft || (resumed && !lastConversationId && !resumeError)))) && (
          <ConversationChat
            key={conversationId ?? 'new'}
            conversationId={conversationId}
            onSent={(id) => {
              if (!conversationId) navigate(`/assistant/${id}`, { replace: true })
              updated()
            }}
          />
        )}
      </section>
      {editing && (
        <Modal title="重命名会话" onClose={() => !busy && setEditing(null)}>
          <form
            onSubmit={async (e) => {
              e.preventDefault()
              const title = String(new FormData(e.currentTarget).get('title') ?? '').trim()
              setBusy(true)
              try {
                const saved = await write<Conversation>(
                  `/conversations/${editing.id}`,
                  { title, expectedRevision: editing.revision },
                  'PATCH',
                )
                setRenamed((previous) => ({ ...previous, [saved.id]: saved }))
                setEditing(null)
                updated()
              } catch (e) {
                setFailure((e as Error).message)
              } finally {
                setBusy(false)
              }
            }}
          >
            <label>
              会话名称
              <input name="title" required maxLength={120} defaultValue={editing.title} autoFocus />
            </label>
            <ErrorNotice>{failure}</ErrorNotice>
            <div className="form-actions">
              <button type="button" onClick={() => setEditing(null)}>
                取消
              </button>
              <BusyButton busy={busy} className="primary">
                保存
              </BusyButton>
            </div>
          </form>
        </Modal>
      )}
      {deleting && (
        <Modal title="删除会话" onClose={() => !busy && setDeleting(null)}>
          <p>删除“{deleting.title}”及其中未关联工作的消息？此操作不能撤销。</p>
          {!!impact?.retainedSources && (
            <p>其中 {impact.retainedSources} 条消息已作为工作或报告来源，将保留在业务记录中。</p>
          )}
          <ErrorNotice>{failure}</ErrorNotice>
          <div className="form-actions">
            <button disabled={busy} onClick={() => setDeleting(null)}>
              取消
            </button>
            <BusyButton
              busy={busy}
              className="danger"
              onClick={async () => {
                setBusy(true)
                try {
                  await write(
                    `/conversations/${deleting.id}`,
                    { expectedRevision: deleting.revision },
                    'DELETE',
                  )
                  const key = `composer:${deleting.id}`
                  ;(drafts[key] as Composer | undefined)?.files.forEach((file) =>
                    URL.revokeObjectURL(file.url),
                  )
                  setDraft(key, undefined)
                  setOlder((rows) => rows.filter((row) => row.id !== deleting.id))
                  setRemoved((previous) => [...previous, deleting.id])
                  if (lastConversationId === deleting.id) rememberConversation(null)
                  if (conversationId === deleting.id) navigate('/assistant', { replace: true })
                  setDeleting(null)
                  updated()
                  notify('会话已删除')
                } catch (e) {
                  setFailure((e as Error).message)
                } finally {
                  setBusy(false)
                }
              }}
            >
              确认删除
            </BusyButton>
          </div>
        </Modal>
      )}
    </div>
  )
}
