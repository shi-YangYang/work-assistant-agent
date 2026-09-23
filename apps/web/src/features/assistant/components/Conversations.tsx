import utilitiesStyles from '../../../styles/utilities.module.css'
import layoutStyles from '../../../styles/layout.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import styles from './Conversations.module.css'
import type { Conversation, Page } from '@paa/api-contracts'
import { ApiError } from '@web/api/client'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { FormField } from '@web/components/FormField'
import { Modal } from '@web/components/Modal'
import {
  conversationPath,
  conversationsPath,
  deleteConversation,
  renameConversation,
} from '@web/features/assistant/api/requests'
import { restoreConversation } from '@web/features/assistant/api/restore-conversation'
import { ConversationChat } from '@web/features/assistant/components/ConversationChat'
import { ConversationPicker } from '@web/features/assistant/components/ConversationPicker'
import type { Composer } from '@web/features/assistant/lib/audio-capture'
import { useResource } from '@web/hooks/useResource'
import { useWorkspace } from '@web/lib/workspace'
import { Plus } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'

export function Assistant({ conversationId }: { conversationId?: string }) {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const { drafts, setDraft, notify, lastConversationId, rememberConversation } = useWorkspace()
  const explicitNew = params.get('new') === '1'
  const showConversations = params.get('conversations') === '1'
  const [resumed, setResumed] = useState(false)
  const [resumeError, setResumeError] = useState<Error | string>('')
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
  const [failure, setFailure] = useState<Error | string>('')
  const [editing, setEditing] = useState<Conversation | null>(null)
  const [titleError, setTitleError] = useState('')
  const [deleting, setDeleting] = useState<Conversation | null>(null)
  const [impact, setImpact] = useState<{ retainedSources: number } | null>(null)
  const [older, setOlder] = useState<Conversation[]>([])
  const [cursor, setCursor] = useState<string | null | undefined>()
  const [removed, setRemoved] = useState<string[]>([])
  const [renamed, setRenamed] = useState<Record<string, Conversation>>({})
  const list = useResource<Page<Conversation>>(conversationsPath(search))
  const current = useResource<Conversation>(conversationPath(conversationId))
  const [chatSession, setChatSession] = useState({
    routeId: conversationId,
    createdId: undefined as string | undefined,
    key: 0,
  })
  if (chatSession.routeId !== conversationId) {
    // First-send navigation keeps the composer; switching conversations still resets local UI.
    const adoptingCreated = !!conversationId && chatSession.createdId === conversationId
    setChatSession({
      routeId: conversationId,
      createdId: adoptingCreated ? chatSession.createdId : undefined,
      key: adoptingCreated ? chatSession.key : chatSession.key + 1,
    })
  }
  const createdHere =
    !!chatSession.createdId &&
    (!conversationId || conversationId === chatSession.createdId) &&
    !current.error
  useEffect(() => {
    if (conversationId || explicitNew || newDraft || createdHere) return
    let active = true
    const controller = new AbortController()
    void restoreConversation(lastConversationId, controller.signal)
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
        if (active) setResumeError(error as Error)
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [
    conversationId,
    explicitNew,
    newDraft,
    createdHere,
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
    <div className={styles['assistant-workspace']}>
      <section className={styles['conversation-main']}>
        <header className={styles['conversation-heading']}>
          <h2 title={current.data?.title}>{current.data?.title ?? '工作助手'}</h2>
          <button onClick={create}>
            <Plus size={16} />
            新会话
          </button>
          <ConversationPicker
            picker={picker}
            setExpanded={setExpanded}
            closePicker={closePicker}
            pickerButton={pickerButton}
            expanded={expanded}
            search={search}
            setSearch={setSearch}
            setOlder={setOlder}
            setCursor={setCursor}
            list={list}
            items={items}
            conversationId={conversationId}
            stopBeforeAction={stopBeforeAction}
            setEditing={(next) => {
              setTitleError('')
              setFailure('')
              setEditing(next)
            }}
            setImpact={setImpact}
            setDeleting={setDeleting}
            setFailure={setFailure}
            nextCursor={nextCursor}
          />
        </header>
        <ErrorNotice>{failure || (conversationId ? current.error : '')}</ErrorNotice>
        {!conversationId && !explicitNew && !newDraft && !createdHere && (
          <>
            <ErrorNotice retry={() => setResumeRevision((value) => value + 1)}>
              {resumeError}
            </ErrorNotice>
            {(!resumed || lastConversationId) && !resumeError && (
              <p className={utilitiesStyles['muted']}>正在打开上次会话…</p>
            )}
          </>
        )}
        {(current.data ||
          createdHere ||
          (!conversationId &&
            (explicitNew || newDraft || (resumed && !lastConversationId && !resumeError)))) && (
          <ConversationChat
            key={chatSession.key}
            conversationId={conversationId}
            onSent={(id) => {
              if (!conversationId) {
                setChatSession((previous) => ({ ...previous, createdId: id }))
                navigate(`/assistant/${id}`, { replace: true })
              }
              rememberConversation(id)
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
              if (!title) {
                setTitleError('请输入会话名称')
                return
              }
              setTitleError('')
              setFailure('')
              setBusy(true)
              try {
                const saved = await renameConversation(editing, {
                  title,
                  expectedRevision: editing.revision,
                })
                setRenamed((previous) => ({ ...previous, [saved.id]: saved }))
                setEditing(null)
                updated()
              } catch (e) {
                if (e instanceof ApiError) setTitleError(e.fieldErrors.title || '')
                setFailure(e as Error)
              } finally {
                setBusy(false)
              }
            }}
          >
            <FormField
              label="会话名称"
              name="title"
              required
              maxLength={120}
              defaultValue={editing.title}
              autoFocus
              error={titleError}
              onChange={() => setTitleError('')}
            />
            <ErrorNotice>{failure}</ErrorNotice>
            <div className={layoutStyles['form-actions']}>
              <button type="button" onClick={() => setEditing(null)}>
                取消
              </button>
              <BusyButton busy={busy} className={controlsStyles['primary']}>
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
          <div className={layoutStyles['form-actions']}>
            <button disabled={busy} onClick={() => setDeleting(null)}>
              取消
            </button>
            <BusyButton
              busy={busy}
              className={controlsStyles['danger']}
              onClick={async () => {
                setBusy(true)
                try {
                  await deleteConversation(deleting, { expectedRevision: deleting.revision })
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
                  setFailure(e as Error)
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
