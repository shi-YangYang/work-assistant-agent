import type { BusinessAction, WorkMessage } from '@paa/api-contracts'
import { Modal } from '@web/components/Modal'
import {
  conversationMessagesPath,
  orphanActionsPath,
  uploadAttachment,
} from '@web/features/assistant/api/requests'
import { ChatHistory } from '@web/features/assistant/components/ChatHistory'
import { ComposerAttachments } from '@web/features/assistant/components/ComposerAttachments'
import type { PreviewImage } from '@web/features/assistant/components/ImageGallery'
import { ImageGallery } from '@web/features/assistant/components/ImageGallery'
import { MessageComposer } from '@web/features/assistant/components/MessageComposer'
import { PdfPreview } from '@web/features/assistant/components/PdfPreview'
import { useMessageSubmission } from '@web/features/assistant/hooks/useMessageSubmission'
import { useRecording } from '@web/features/assistant/hooks/useRecording'
import type { Composer } from '@web/features/assistant/lib/audio-capture'
import {
  droppedFiles,
  fileKind,
  fileSelectionError,
  isHeif,
  updateSendingDraft,
} from '@web/features/assistant/utils/files'
import { usePagedResource } from '@web/hooks/usePagedResource'
import { useResource } from '@web/hooks/useResource'
import { useRetryWait } from '@web/hooks/useRetryWait'
import { useWorkspace } from '@web/lib/workspace'
import { useEffect, useMemo, useRef, useState } from 'react'

export function ConversationChat({
  conversationId,
  onSent,
}: {
  conversationId?: string
  onSent: (conversationId: string) => void
}) {
  const composerKey = `composer:${conversationId ?? 'new'}`
  const { drafts, setDraft, notify, identity } = useWorkspace()
  const storedComposer = drafts[composerKey] as Composer | undefined
  const composer = useMemo(
    () => storedComposer ?? { text: '', files: [], key: '' },
    [storedComposer],
  )
  const { data, error, refresh, loadMore, loading } = usePagedResource<WorkMessage>(
    conversationMessagesPath(conversationId),
    'createdAt',
    2000,
  )
  const actionReceipts = useResource<{ items: BusinessAction[] }>(
    orphanActionsPath(conversationId),
    3000,
  )
  const [previewUploading, setPreviewUploading] = useState(false)
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
    onSent,
    previewUploading,
    capturing,
    active,
    setLimitError,
    setSendError,
    retryWait,
    refresh,
  })
  const locked = busy || pending || previewUploading
  const textInput = useRef<HTMLTextAreaElement>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const atBottomRef = useRef(true)
  const [newReply, setNewReply] = useState(false)
  const composerRef = useRef(composer)
  useEffect(() => {
    composerRef.current = composer
  }, [composer])
  const change = (next: Composer) => {
    composerRef.current = next
    setDraft(
      composerKey,
      next.text || next.files.length || next.replyTo || next.pending
        ? { ...next, key: next.key || crypto.randomUUID() }
        : undefined,
    )
  }
  useEffect(() => {
    const scroll = scroller.current
    const content = scroll?.querySelector('.chat-content')
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
      composer.files.length >= 4 ||
      composer.files.some((item) => fileKind(item.file) === 'audio') ||
      composer.files.reduce((sum, item) => sum + item.file.size, 0) >= 20 * 1024 * 1024
    ) {
      setLimitError('每次最多 4 个附件、20 MiB，其中最多一段语音；请先移除一个附件')
      return
    }
    setSendError('')
    await capture.current?.start(
      20 * 1024 * 1024 - composer.files.reduce((sum, item) => sum + item.file.size, 0),
    )
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
        setPreviewUploading(true)
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
          if (active.current) setPreviewUploading(false)
        }
      },
    }))
  const messages = [...(data?.items ?? [])].sort((a, b) => a.createdAt.localeCompare(b.createdAt))
  const nextCursor = data?.nextCursor
  return (
    <div
      className={`assistant-page${dragging ? ' file-dragging' : ''}`}
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
      {dragging && <div className="file-drop-hint">松开以添加附件</div>}
      {limitError && (
        <Modal title="无法添加附件" onClose={() => setLimitError('')}>
          <p>{limitError}</p>
          <div className="form-actions">
            <button className="primary" onClick={() => setLimitError('')}>
              知道了
            </button>
          </div>
        </Modal>
      )}
      {newReply && (
        <button
          className="new-reply"
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
        scroller={scroller}
        atBottomRef={atBottomRef}
        setNewReply={setNewReply}
        refresh={refresh}
        error={error}
        nextCursor={nextCursor}
        loading={loading}
        loadMore={loadMore}
        messages={messages}
        conversationId={conversationId}
        data={data}
        identity={identity}
        locked={locked}
        composer={composer}
        notify={notify}
        change={change}
        textInput={textInput}
        actionReceipts={actionReceipts}
      />
      <MessageComposer
        send={send}
        addFiles={addFiles}
        composer={composer}
        locked={locked}
        change={change}
        textInput={textInput}
        busy={busy}
        previewUploading={previewUploading}
        pending={pending}
        sendError={sendError}
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
    </div>
  )
}
