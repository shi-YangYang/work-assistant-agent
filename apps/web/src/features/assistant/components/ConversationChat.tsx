import layoutStyles from '../../../styles/layout.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import styles from './ConversationChat.module.css'
import type {
  AssistantInteraction,
  BusinessAction,
  JobFeedback,
  PersonaId,
  WorkMessage,
} from '@paa/api-contracts'
import { Modal } from '@web/components/Modal'
import { AssistantNotice, type AssistantNoticeData } from './AssistantNotice'
import {
  conversationMessagesPath,
  orphanActionsPath,
  uploadAttachment,
} from '@web/features/assistant/api/requests'
import { AssistantSuggestions } from '@web/features/assistant/components/AssistantSuggestions'
import { exampleText } from '@web/features/assistant/utils/session'
import { ChatHistory } from '@web/features/assistant/components/ChatHistory'
import { ComposerAttachments } from '@web/features/assistant/components/ComposerAttachments'
import type { PreviewImage } from '@web/features/assistant/components/ImageGallery'
import { ImageGallery } from '@web/features/assistant/components/ImageGallery'
import { useWorkReference } from '../hooks/useWorkReference'
import { MessageComposer } from '@web/features/assistant/components/MessageComposer'
import { PdfPreview } from '@web/features/assistant/components/PdfPreview'
import type { PersonaInteraction } from '@web/features/assistant/hooks/useConversationPersona'
import { useAssistantInteraction } from '../hooks/useAssistantInteraction'
import type { useExecutionMode } from '../hooks/useExecutionMode'
import { ExecutionModePicker } from './ExecutionModePicker'
import { QuestionPanel } from './QuestionPanel'
import { useAssistantTask } from '@web/features/assistant/hooks/useAssistantTask'
import { useContextUsage } from '@web/features/assistant/hooks/useContextUsage'
import { useMessageSubmission } from '@web/features/assistant/hooks/useMessageSubmission'
import { useRecording } from '@web/features/assistant/hooks/useRecording'
import type { Composer } from '@web/features/assistant/lib/audio-capture'
import {
  MAX_ATTACHMENTS,
  MAX_AUDIO_ATTACHMENTS,
} from '@web/features/assistant/utils/attachment-limits'
import {
  droppedFiles,
  fileKind,
  fileSelectionError,
  isHeif,
  updateSendingDraft,
} from '@web/features/assistant/utils/files'
import { usePagedResource } from '@web/hooks/usePagedResource'
import { useQueryResource } from '@web/hooks/useQueryResource'
import { identityScope } from '@web/lib/session-drafts'
import { assistantQuery } from '../api/queries'
import {
  type RegisterConversationRefresh,
  useConversationRefresh,
} from '../hooks/useConversationRefresh'
import { useRetryWait } from '@web/hooks/useRetryWait'
import { useWorkspace } from '@web/lib/workspace'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

export function ConversationChat({
  conversationId,
  personaId,
  interaction,
  execution,
  onSent,
  registerRefresh,
  pageNotice,
}: {
  conversationId?: string
  personaId: PersonaId
  interaction: PersonaInteraction
  execution: ReturnType<typeof useExecutionMode>
  onSent: (conversationId: string, personaId: PersonaId) => void
  registerRefresh?: RegisterConversationRefresh
  pageNotice?: AssistantNoticeData
}) {
  const composerKey = `composer:${conversationId ?? 'new'}`
  const { drafts, setDraft, notify, identity } = useWorkspace()
  const storedComposer = drafts[composerKey] as Composer | undefined
  const composer = useMemo(
    () => storedComposer ?? { text: '', files: [], key: '' },
    [storedComposer],
  )
  const { data, error, refresh, invalidate, loadMore, loading } = usePagedResource<WorkMessage>(
    conversationMessagesPath(conversationId),
    'createdAt',
    0,
    { scope: identityScope(identity) },
  )
  const messages = useMemo(
    () => [...(data?.items ?? [])].sort((a, b) => a.createdAt.localeCompare(b.createdAt)),
    [data],
  )
  const actionReceipts = useQueryResource(
    assistantQuery<{ items: BusinessAction[] }>(
      orphanActionsPath(conversationId),
      identityScope(identity),
    ),
  )
  const synchronizedFeedback = useRef('')
  const synchronizeResult = (feedback?: JobFeedback) => {
    if (feedback) {
      const key = JSON.stringify([
        feedback.jobId,
        feedback.attempt,
        feedback.fence,
        feedback.seq,
        feedback.state,
        feedback.stage,
      ])
      if (synchronizedFeedback.current === key) return
      synchronizedFeedback.current = key
    }
    void invalidate()
    if (feedback && ['queued', 'running'].includes(feedback.state)) return
    void actionReceipts.invalidate()
    void assistantQuery<{ items: AssistantInteraction[] }>(
      conversationId ? `/conversations/${conversationId}/interactions` : null,
      identityScope(identity),
    )?.invalidate()
  }
  const task = useAssistantTask(conversationId, messages, synchronizeResult, true)
  const incomingQuestions = useMemo(
    () => [
      ...messages.flatMap((message) =>
        message.businessUnavailable ? [] : (message.interactions ?? []),
      ),
      ...(task.feedback?.interactions ?? []),
    ],
    [messages, task.feedback?.interactions],
  )
  const questions = useAssistantInteraction(
    conversationId,
    incomingQuestions,
    (continuation) => {
      if (continuation) task.accepted(continuation)
      else void task.refresh()
      void invalidate()
      void actionReceipts.invalidate()
    },
    true,
  )
  const questionsByMessage = new Map<string, AssistantInteraction[]>()
  for (const question of questions.items)
    questionsByMessage.set(question.messageId, [
      ...(questionsByMessage.get(question.messageId) ?? []),
      question,
    ])
  const [previewBusy, setPreviewUploading] = useState(false)
  const previewUploading = previewBusy || (!!composer.uploading && !composer.sending)
  const [gallery, setGallery] = useState<number | null>(null)
  const [pdf, setPdf] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const dragDepth = useRef(0)
  const [sendError, setSendError] = useState<Error | string>('')
  const retryWait = useRetryWait(sendError)
  const pending = !!composer.pending
  const [limitError, setLimitError] = useState('')
  const { captureState, capturing, seconds, capture, active } = useRecording(
    composerKey,
    setDraft,
    setSendError,
    setLimitError,
  )
  const { busy, sendingRef, send } = useMessageSubmission({
    composer,
    composerKey,
    conversationId,
    personaId,
    interaction,
    onSent,
    previewUploading,
    capturing,
    active,
    setLimitError,
    setSendError,
    retryWait,
    refresh: invalidate,
    task,
  })
  const locked =
    busy ||
    pending ||
    !!questions.busy ||
    previewUploading ||
    interaction.busy === 'persona' ||
    execution.saving
  const textInput = useRef<HTMLTextAreaElement>(null)
  const workReference = useWorkReference(composerKey, locked, textInput)
  const scroller = useRef<HTMLDivElement>(null)
  const pageElement = useRef<HTMLDivElement>(null)
  const composerElement = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    const page = pageElement.current
    const element = composerElement.current
    if (!page || !element) return
    const update = () => {
      page.style.setProperty('--composer-height', `${element.getBoundingClientRect().height}px`)
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(element)
    return () => {
      observer.disconnect()
      page.style.removeProperty('--composer-height')
    }
  }, [])
  const atBottomRef = useRef(true)
  const [newReply, setNewReply] = useState(false)
  const composerRef = useRef(composer)
  useEffect(() => {
    composerRef.current = composer
  }, [composer])
  const change = (next: Composer) => {
    next = { ...next, submissionPersonaId: undefined }
    composerRef.current = next
    setDraft(
      composerKey,
      next.text ||
        next.files.length ||
        next.replyTo ||
        next.pending ||
        next.personaId ||
        next.executionMode ||
        next.deliverableReference ||
        next.workReference
        ? { ...next, key: next.key || crypto.randomUUID() }
        : undefined,
    )
  }
  useEffect(() => {
    const scroll = scroller.current
    const content = scroll?.querySelector('[data-chat-content]')
    if (!scroll || !content) return
    const observer = new ResizeObserver(() => {
      if (atBottomRef.current) scroll.scrollTop = scroll.scrollHeight
      else setNewReply(true)
    })
    observer.observe(content)
    return () => observer.disconnect()
  }, [])
  async function addFiles(files: File[]) {
    if (!files.length || locked || capturing || sendingRef.current) return
    const existing = composerRef.current
    const error = fileSelectionError([...existing.files.map((item) => item.file), ...files])
    if (error) {
      setLimitError(error)
      return
    }
    change({
      ...existing,
      key: '',
      files: [
        ...existing.files,
        ...files.map((file) => ({ id: crypto.randomUUID(), file, url: URL.createObjectURL(file) })),
      ],
    })
    setSendError('')
  }
  async function startRecording() {
    if (locked) return
    if (
      composer.files.length >= MAX_ATTACHMENTS ||
      composer.files.filter((item) => fileKind(item.file) === 'audio').length >=
        MAX_AUDIO_ATTACHMENTS
    ) {
      setLimitError('每次最多 9 个附件，其中最多 3 段语音；请先移除一个附件')
      return
    }
    setSendError('')
    await capture.current?.start()
  }
  const previewImages: PreviewImage[] = composer.files
    .filter((item) => fileKind(item.file) === 'image')
    .map((item) => ({
      id: item.id,
      name: item.file.name,
      original: item.url,
      src: item.attachment?.previewUrl ?? (isHeif(item.file) ? undefined : item.url),
      warnings: item.attachment?.image?.warnings,
      prepare: async () => {
        if (locked || capturing || sendingRef.current) throw new Error('请等待当前操作结束后再预览')
        if (!interaction.acquire('preview')) throw new Error('请等待人设保存后再预览')
        setPreviewUploading(true)
        setDraft(composerKey, (previous: Composer | undefined) =>
          updateSendingDraft(previous, composer.key, { uploading: item.id }),
        )
        try {
          const form = new FormData()
          form.append('file', item.file)
          const attachment = await uploadAttachment({ method: 'POST', body: form })
          setDraft(composerKey, (previous: Composer | undefined) =>
            updateSendingDraft(previous, composer.key, {
              files:
                previous?.files.map((file) =>
                  file.id === item.id ? { ...file, attachment, failed: false } : file,
                ) ?? [],
            }),
          )
          return attachment.previewUrl ?? attachment.url
        } finally {
          setDraft(composerKey, (previous: Composer | undefined) =>
            updateSendingDraft(previous, composer.key, { uploading: undefined }),
          )
          interaction.release('preview')
          if (active.current) setPreviewUploading(false)
        }
      },
    }))
  const latestJob =
    [...messages].reverse().find((message) => !message.businessUnavailable && message.job)?.job ??
    null
  const contextJob =
    task.job && (task.running || !latestJob || task.job.updatedAt >= latestJob.updatedAt)
      ? task.job
      : latestJob
  const context = useContextUsage(conversationId, contextJob, true)
  const refreshChat = () => {
    void refresh()
    void actionReceipts.refresh()
    questions.refresh()
    void context.refresh()
    void task.synchronize()
    void assistantQuery(`/conversations/${conversationId}`, identityScope(identity))?.refresh()
  }
  useConversationRefresh(conversationId, refreshChat, registerRefresh)
  const receiveContext = context.receive
  useEffect(() => {
    if (task.job) receiveContext(task.job, task.feedback)
  }, [task.job, task.feedback, receiveContext])
  const nextCursor = data?.nextCursor
  const empty = !messages.length && !error && (!conversationId || !!data)
  const notice = (
    [
      { error: sendError || execution.error },
      { error: workReference.error ?? '', retry: workReference.retry },
      {
        error:
          task.error ||
          error ||
          actionReceipts.error ||
          (!questions.waiting ? questions.error : ''),
        retry: refreshChat,
      },
      ...(pageNotice ? [pageNotice] : []),
    ] satisfies AssistantNoticeData[]
  ).find((item) => item.error)
  return (
    <>
      <AssistantNotice notice={notice} pending={pending && !busy} />
      <div
        ref={pageElement}
        className={styles['assistant-page']}
        data-empty={empty}
        onDragEnter={(event) => {
          if (!event.dataTransfer.types.includes('Files')) return
          event.preventDefault()
          dragDepth.current++
          if (!locked && !capturing) setDragging(true)
        }}
        onDragOver={(event) => {
          if (event.dataTransfer.types.includes('Files')) {
            event.preventDefault()
            event.dataTransfer.dropEffect = locked || capturing ? 'none' : 'copy'
          }
        }}
        onDragLeave={() => {
          dragDepth.current = Math.max(0, dragDepth.current - 1)
          if (!dragDepth.current) setDragging(false)
        }}
        onDrop={(event) => {
          if (!event.dataTransfer.types.includes('Files')) return
          event.preventDefault()
          dragDepth.current = 0
          setDragging(false)
          if (locked || capturing) return
          const selected = droppedFiles(event.dataTransfer)
          if (selected.error) setLimitError(selected.error)
          else void addFiles(selected.files)
        }}
      >
        {gallery !== null && previewImages[gallery] && (
          <ImageGallery images={previewImages} initial={gallery} onClose={() => setGallery(null)} />
        )}
        {pdf && <PdfPreview name={pdf.name} file={pdf} onClose={() => setPdf(null)} />}
        {dragging && <div className={styles['file-drop-hint']}>松开以添加附件</div>}
        {limitError && (
          <Modal title="无法添加附件" onClose={() => setLimitError('')}>
            <p>{limitError}</p>
            <div className={layoutStyles['form-actions']}>
              <button className={controlsStyles['primary']} onClick={() => setLimitError('')}>
                知道了
              </button>
            </div>
          </Modal>
        )}
        {newReply && (
          <button
            className={styles['new-reply']}
            onClick={() => {
              if (scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight
              atBottomRef.current = true
              setNewReply(false)
            }}
          >
            有新回复 · 回到最新
          </button>
        )}
        <ChatHistory
          onContextUpdate={context.receive}
          task={task}
          onContinuation={(continuation) => {
            if (continuation) task.accepted(continuation)
            else void task.refresh()
            questions.refresh()
            void actionReceipts.invalidate()
            void invalidate()
          }}
          scroller={scroller}
          atBottomRef={atBottomRef}
          setNewReply={setNewReply}
          refresh={refresh}
          invalidate={invalidate}
          onFeedback={synchronizeResult}
          error={error}
          nextCursor={nextCursor}
          loading={loading}
          loadMore={loadMore}
          messages={messages.map((message) => ({
            ...message,
            interactions: questions.unavailable
              ? []
              : (questionsByMessage.get(message.id) ?? message.interactions),
          }))}
          conversationId={conversationId}
          data={data}
          identity={identity}
          locked={locked}
          composer={composer}
          change={change}
          textInput={textInput}
          actionReceipts={actionReceipts}
          onDeliverable={(reference, title, text) => {
            change({
              ...composer,
              deliverableReference: reference,
              deliverableTitle: title,
              text: text
                ? composer.text.trim()
                  ? `${composer.text}\n${text}`
                  : text
                : composer.text,
              key: '',
            })
            textInput.current?.focus()
          }}
        />
        <MessageComposer
          workReference={workReference}
          contextKey={`context:${identity.company.id}:${identity.member.id}:${conversationId ?? 'new'}`}
          contextUsage={context.usage}
          contextUnavailable={context.unavailable}
          contextLoading={context.loading}
          containerRef={composerElement}
          empty={empty}
          dragging={dragging}
          send={send}
          task={task}
          addFiles={addFiles}
          composer={composer}
          locked={locked}
          change={change}
          textInput={textInput}
          busy={busy}
          previewUploading={previewUploading}
          personaSaving={interaction.busy === 'persona' || execution.saving}
          executionControl={
            <ExecutionModePicker
              value={execution.selected}
              acknowledged={execution.acknowledged}
              disabled={execution.disabled || task.blocked || locked || capturing}
              onChange={(mode, acknowledged) => void execution.choose(mode, acknowledged)}
            />
          }
          questionPanel={
            questions.waiting && (
              <QuestionPanel
                key={`${questions.waiting.id}:${questions.waiting.revision}`}
                item={questions.waiting}
                busy={!!questions.busy}
                disabled={busy || task.blocked || execution.saving}
                error={questions.error}
                onAnswer={(answers) => {
                  if (interaction.acquire('message'))
                    void questions
                      .respond(questions.waiting!, answers)
                      .finally(() => interaction.release('message'))
                }}
                onCancel={() => {
                  if (interaction.acquire('message'))
                    void questions
                      .respond(questions.waiting!)
                      .finally(() => interaction.release('message'))
                }}
              />
            )
          }
          pending={pending}
          retryWait={retryWait}
          recording={{
            state: captureState,
            seconds,
            start: startRecording,
            stop: () => capture.current?.stop(),
          }}
        >
          <ComposerAttachments
            composer={composer}
            locked={locked}
            setGallery={setGallery}
            previewImages={previewImages}
            setPdf={setPdf}
            change={change}
          />
        </MessageComposer>
        {empty && (
          <AssistantSuggestions
            admin={identity.member.role === 'admin'}
            disabled={locked}
            onChoose={(text) => {
              const next = exampleText(composer.text, text)
              if (next === composer.text) notify('输入框已有内容，请继续编辑；示例没有覆盖它。')
              else change({ ...composer, text: next, key: '' })
              textInput.current?.focus()
            }}
          />
        )}
      </div>
    </>
  )
}
