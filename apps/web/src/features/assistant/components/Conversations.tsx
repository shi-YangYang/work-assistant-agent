import utilitiesStyles from '../../../styles/utilities.module.css'
import layoutStyles from '../../../styles/layout.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import styles from './Conversations.module.css'
import type { Conversation } from '@paa/api-contracts'
import { ApiError } from '@web/api/client'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { FormField } from '@web/components/FormField'
import { Modal } from '@web/components/Modal'
import {
  conversationPath,
  deleteConversation,
  renameConversation,
} from '@web/features/assistant/api/requests'
import { latestChat, restoreConversation } from '@web/features/assistant/api/restore-conversation'
import { ConversationChat } from '@web/features/assistant/components/ConversationChat'
import { PersonaPicker } from '@web/features/assistant/components/PersonaPicker'
import { useExecutionMode } from '../hooks/useExecutionMode'
import { useConversationPersona } from '@web/features/assistant/hooks/useConversationPersona'
import {
  type RegisterConversationRefresh,
  useConversationRefresh,
} from '../hooks/useConversationRefresh'
import { ConversationPicker } from '@web/features/assistant/components/ConversationPicker'
import type { Composer } from '@web/features/assistant/lib/audio-capture'
import { useConversationSearch } from '@web/features/assistant/hooks/useConversationSearch'
import { useQueryResource } from '@web/hooks/useQueryResource'
import { identityScope } from '@web/lib/session-drafts'
import { assistantQuery, saveConversationQuery } from '../api/queries'
import { useWorkspace } from '@web/lib/workspace'
import { MessageSquare, SquarePen } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'

export function Assistant({ conversationId }: { conversationId?: string }) {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const { identity, drafts, setDraft, notify, lastConversationId, rememberConversation } =
    useWorkspace()
  const workEntry = params.get('workId') || undefined
  const [resolvedWorkEntry, setResolvedWorkEntry] = useState<string | undefined>()
  const needsWorkRestore = !!workEntry && !conversationId && resolvedWorkEntry !== workEntry
  const explicitNew = !workEntry && params.get('new') === '1'
  const showConversations = params.get('conversations') === '1'
  const [resumed, setResumed] = useState(false)
  const [resumeError, setResumeError] = useState<Error | string>('')
  const [resumeRevision, setResumeRevision] = useState(0)
  const attemptedResumeRevision = useRef(0)
  const newDraft = !!drafts['composer:new']
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
  const [removed, setRemoved] = useState<string[]>([])
  const [renamed, setRenamed] = useState<Record<string, Conversation>>({})
  const list = useConversationSearch(expanded)
  const { search, setSearch } = list
  const query = assistantQuery<Conversation>(
    conversationPath(conversationId),
    identityScope(identity),
  )
  const current = useQueryResource(query)
  const chatRefresh = useRef<(() => void) | null>(null)
  const registerRefresh = useCallback<RegisterConversationRefresh>((refresh) => {
    chatRefresh.current = refresh
    return () => {
      if (chatRefresh.current === refresh) chatRefresh.current = null
    }
  }, [])
  useConversationRefresh(conversationId, () => {
    if (chatRefresh.current) chatRefresh.current()
    else void current.refresh()
  })
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
    if (
      conversationId ||
      (!needsWorkRestore &&
        (explicitNew ||
          newDraft ||
          createdHere ||
          (resolvedWorkEntry === workEntry && !!workEntry)))
    )
      return
    let active = true
    const controller = new AbortController()
    const fresh = resumeRevision !== attemptedResumeRevision.current
    attemptedResumeRevision.current = resumeRevision
    void (
      needsWorkRestore
        ? latestChat(controller.signal, identityScope(identity), { fresh })
        : restoreConversation(lastConversationId, controller.signal, identityScope(identity), {
            fresh,
          })
    )
      .then((id) => {
        if (!active) return
        rememberConversation(id)
        setResumeError('')
        setResumed(true)
        if (workEntry && !id) setResolvedWorkEntry(workEntry)
        if (id)
          navigate(
            `/assistant/${id}${workEntry ? `?workId=${encodeURIComponent(workEntry)}` : showConversations ? '?conversations=1' : ''}`,
            {
              replace: true,
            },
          )
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
    needsWorkRestore,
    workEntry,
    resolvedWorkEntry,
    identity,
  ])
  useEffect(() => {
    if (current.data && current.data.id === conversationId) rememberConversation(current.data.id)
  }, [current.data, conversationId, rememberConversation])
  const items = (list.data?.items ?? [])
    .filter(
      (item, i, all) =>
        !removed.includes(item.id) && all.findIndex((row) => row.id === item.id) === i,
    )
    .map((item) => (renamed[item.id]?.revision >= item.revision ? renamed[item.id] : item))
  const nextCursor = list.data?.nextCursor
  const updated = (saved?: Conversation) => {
    if (saved) saveConversationQuery(saved, identityScope(identity))
    else void current.invalidate()
    if (expanded) list.refresh()
  }
  const persona = useConversationPersona(conversationId, current.data, updated)
  const execution = useExecutionMode(conversationId, current.data, persona.interaction, updated)
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
          <MessageSquare size={17} />
          <h2 title={current.data?.title}>{current.data?.title ?? '工作助手'}</h2>
          {!current.data && <span className={styles['conversation-caption']}>随时为你准备</span>}
          <PersonaPicker
            value={persona.selected}
            disabled={persona.disabled || !!persona.interaction.busy}
            onChange={(value) => void persona.choose(value)}
          />
          <button
            className={`${controlsStyles['icon-button']} ${styles['new-conversation']}`}
            aria-label="新会话"
            title="新会话"
            onClick={create}
          >
            <SquarePen size={18} />
          </button>
          <ConversationPicker
            picker={picker}
            setExpanded={setExpanded}
            closePicker={closePicker}
            pickerButton={pickerButton}
            expanded={expanded}
            search={search}
            setSearch={setSearch}
            loadMore={list.loadMore}
            loading={list.loading}
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
        <ErrorNotice>{persona.error || failure}</ErrorNotice>
        <ErrorNotice retry={() => void current.refresh()}>
          {conversationId ? current.error : ''}
        </ErrorNotice>
        {!conversationId && (needsWorkRestore || (!explicitNew && !newDraft && !createdHere)) && (
          <>
            <ErrorNotice retry={() => setResumeRevision((value) => value + 1)}>
              {resumeError}
            </ErrorNotice>
            {(needsWorkRestore || !resumed || lastConversationId) && !resumeError && (
              <p className={utilitiesStyles['muted']}>正在打开上次会话…</p>
            )}
          </>
        )}
        {!needsWorkRestore &&
          (current.data ||
            createdHere ||
            (!conversationId &&
              (explicitNew || newDraft || (resumed && !lastConversationId && !resumeError)))) && (
            <ConversationChat
              key={chatSession.key}
              conversationId={conversationId}
              personaId={persona.selected}
              interaction={persona.interaction}
              execution={execution}
              registerRefresh={registerRefresh}
              onSent={(id, sentPersona) => {
                if (!conversationId) {
                  persona.adoptCreated(id, sentPersona)
                  execution.adoptCreated(id)
                  setChatSession((previous) => ({ ...previous, createdId: id }))
                  navigate(
                    `/assistant/${id}${workEntry ? `?workId=${encodeURIComponent(workEntry)}` : ''}`,
                    { replace: true },
                  )
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
                updated(saved)
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
