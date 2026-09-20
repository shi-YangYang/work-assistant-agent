import { ApiError, isCancelled } from '@web/api/client'
import { sendMessage, uploadAttachment } from '@web/features/assistant/api/requests'
import type { Composer } from '@web/features/assistant/lib/audio-capture'
import {
  fileSelectionError,
  messageSubmission,
  updateSendingDraft,
} from '@web/features/assistant/utils/files'
import { useWorkspace } from '@web/lib/workspace'
import { useRef, useState } from 'react'

import type { RefObject } from 'react'
export function useMessageSubmission({
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
}: {
  composer: Composer
  composerKey: string
  conversationId?: string
  onSent: (id: string) => void
  previewUploading: boolean
  capturing: boolean
  active: RefObject<boolean>
  setLimitError: (error: string) => void
  setSendError: (error: Error | string) => void
  retryWait: number
  refresh: () => void
}) {
  const { setDraft, notify, rememberConversation } = useWorkspace()
  const [sending, setBusy] = useState(false)
  const busy = sending || !!composer.sending
  const sendingRef = useRef(false)
  async function send() {
    if (
      sendingRef.current ||
      retryWait ||
      busy ||
      previewUploading ||
      capturing ||
      (!composer.text.trim() && !composer.files.length)
    )
      return
    const selectionError = fileSelectionError(composer.files.map((item) => item.file))
    if (selectionError) {
      setLimitError(selectionError)
      return
    }
    sendingRef.current = true
    setBusy(true)
    setSendError('')
    let current = { ...composer, files: composer.files.map((file) => ({ ...file })) }
    let uploading: string | undefined
    setDraft(composerKey, { ...current, sending: true })
    try {
      if (!current.pending) {
        for (let i = 0; i < current.files.length; i++) {
          if (!current.files[i].attachment) {
            uploading = current.files[i].id
            setDraft(composerKey, (previous: Composer | undefined) =>
              updateSendingDraft(previous, composer.key, { uploading }),
            )
            const form = new FormData()
            form.append('file', current.files[i].file)
            const attachment = await uploadAttachment({ method: 'POST', body: form })
            current = {
              ...current,
              files: current.files.map((file, index) =>
                index === i ? { ...file, attachment, failed: false } : file,
              ),
            }
          }
          setDraft(composerKey, (previous: Composer | undefined) =>
            updateSendingDraft(previous, composer.key, {
              files: current.files,
              uploading: undefined,
            }),
          )
        }
        uploading = undefined
        current.pending = messageSubmission(current, conversationId)
        setDraft(composerKey, (previous: Composer | undefined) =>
          updateSendingDraft(previous, composer.key, { pending: current.pending }),
        )
      }
      const sent = await sendMessage(current.pending.body, current.pending.key)
      current.files.forEach((file) => URL.revokeObjectURL(file.url))
      setDraft(composerKey, (previous: Composer | undefined) =>
        updateSendingDraft(previous, composer.key, null),
      )
      if (active.current) {
        refresh()
        notify('已发送')
        rememberConversation(sent.conversationId)
        onSent(sent.conversationId)
      }
    } catch (e) {
      if (uploading) {
        setDraft(composerKey, (previous: Composer | undefined) =>
          updateSendingDraft(previous, composer.key, {
            files: current.files.map((file) =>
              file.id === uploading ? { ...file, failed: true } : file,
            ),
          }),
        )
      }
      // A structured 4xx rejection is definite, except authentication interruption
      // and an idempotency conflict. Network/5xx/invalid replies remain uncertain.
      if (e instanceof ApiError && [400, 403, 404, 413, 415, 422, 429].includes(e.status)) {
        setDraft(composerKey, (previous: Composer | undefined) =>
          updateSendingDraft(previous, composer.key, { pending: undefined }),
        )
      }
      if (active.current && !isCancelled(e)) {
        if (e instanceof ApiError && [413, 415, 422].includes(e.status) && current.files.length)
          setLimitError(e.message)
        else setSendError(e instanceof Error ? e : '发送未完成')
      }
    } finally {
      setDraft(composerKey, (previous: Composer | undefined) =>
        updateSendingDraft(previous, composer.key, { sending: false, uploading: undefined }),
      )
      sendingRef.current = false
      if (active.current) setBusy(false)
    }
  }
  return { busy, sendingRef, send }
}
