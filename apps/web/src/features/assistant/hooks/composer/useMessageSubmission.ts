import { deleteDraftAttachment } from '@web/api/attachments'
import { attachmentsReady } from '../../lib/attachment-uploads'
import type { ExecutionMode, PersonaId } from '@paa/api-contracts'
import type { useReasoningEffort } from '../preferences/useReasoningEffort'
import type { PersonaInteraction } from '../preferences/useConversationPersona'
import { beginAssistantActivity } from '@web/api/assistant-activity'
import { identityScope } from '@web/lib/session-drafts'
import { ApiError, isCancelled } from '@web/api/client'
import { sendMessage, uploadAttachment } from '@web/features/assistant/api/requests'
import type { Composer } from '@web/features/assistant/lib/audio-capture'
import {
  fileSelectionError,
  messageSubmission,
  updateSendingDraft,
} from '@web/features/assistant/utils/files'
import { useWorkspace } from '@web/lib/workspace'
import { useEffect, useRef, useState } from 'react'

import type { RefObject } from 'react'
export function useMessageSubmission({
  composer,
  composerKey,
  conversationId,
  personaId,
  interaction,
  execution,
  reasoning,
  onSent,
  previewUploading,
  capturing,
  active,
  setLimitError,
  setSendError,
  retryWait,
  refresh,
  task,
  recordedSend,
}: {
  composer: Composer
  composerKey: string
  conversationId?: string
  personaId: PersonaId
  interaction?: PersonaInteraction
  reasoning?: ReturnType<typeof useReasoningEffort>
  execution?: { ready: boolean; selected: ExecutionMode; refresh: () => Promise<void> }
  onSent: (id: string, personaId: PersonaId) => void
  previewUploading: boolean
  capturing: boolean
  active: RefObject<boolean>
  setLimitError: (error: string) => void
  setSendError: (error: Error | string) => void
  retryWait: number
  refresh: () => void
  task?: {
    canSubmit: () => boolean
    accepted: (sent: { conversationId: string; messageId: string; jobId: string }) => void
    refresh: () => Promise<void>
  }
  recordedSend?: RefObject<File | null>
}) {
  const { identity, setDraft, rememberConversation, notify } = useWorkspace()
  const [sending, setBusy] = useState(false)
  const [sendingRecording, setSendingRecording] = useState<{ file: File | null }>({ file: null })
  const directSendingFile = recordedSend?.current ?? sendingRecording.file
  const busy = sending || !!composer.sending
  const sendingRef = useRef(false)
  function finishDirectRecording(file: File, createdConversationId?: string) {
    const destination =
      !conversationId && createdConversationId && active.current
        ? `composer:${createdConversationId}`
        : composerKey
    let retained: Composer | undefined
    setDraft(composerKey, (previous: Composer | undefined) => {
      if (previous?.key !== composer.key) return previous
      previous.files
        .filter((item) => item.file === file)
        .forEach((item) => URL.revokeObjectURL(item.url))
      retained = {
        ...previous,
        key: crypto.randomUUID(),
        files: previous.files.filter((item) => item.file !== file),
        sending: false,
        uploading: undefined,
      }
      return destination === composerKey ? retained : undefined
    })
    if (destination !== composerKey && retained) setDraft(destination, retained)
  }
  useEffect(() => {
    const file = recordedSend?.current
    if (!recordedSend || !file || capturing || !composer.files.some((item) => item.file === file))
      return
    let cancelled = false
    // Wait for the recorder's final data and the updated draft to commit.
    queueMicrotask(() => {
      if (cancelled || !active.current || recordedSend.current !== file) return
      setSendingRecording({ file })
      recordedSend.current = null
      void send(file)
        .then((sent) => {
          if (sent) return
          finishDirectRecording(file)
          if (active.current) notify('语音发送未完成')
        })
        .finally(() => {
          if (active.current)
            setSendingRecording((current) => (current.file === file ? { file: null } : current))
        })
    })
    return () => {
      cancelled = true
    }
  })
  async function send(directFile?: File) {
    if (
      (execution && !execution.ready) ||
      (reasoning && !reasoning.reference()) ||
      (!composer.pending && task && !task.canSubmit()) ||
      sendingRef.current ||
      retryWait ||
      busy ||
      previewUploading ||
      capturing ||
      (!composer.text.trim() && !composer.files.length)
    )
      return
    const files = directFile
      ? composer.files.filter((item) => item.file === directFile)
      : composer.files
    if (directFile && !files.length) return
    if (!directFile && !composer.pending && !attachmentsReady(files)) return
    const selectionError = fileSelectionError(files.map((item) => item.file))
    if (selectionError) {
      if (!directFile) setLimitError(selectionError)
      return
    }
    if (interaction && !interaction.acquire('message')) return
    const activity = beginAssistantActivity(identityScope(identity))
    sendingRef.current = true
    setBusy(true)
    setSendError('')
    let current: Composer & { submissionPersonaId: PersonaId } = {
      ...(directFile ? { text: '', key: crypto.randomUUID() } : composer),
      submissionPersonaId: composer.submissionPersonaId ?? personaId,
      files: files.map((file) => ({ ...file })),
    }
    let uploading: string | undefined
    setDraft(composerKey, { ...(directFile ? composer : current), sending: true })
    try {
      if (!current.pending) {
        if (directFile && !current.files[0].attachment) {
          uploading = current.files[0].id
          const body = new FormData()
          body.append('file', directFile)
          const attachment = await uploadAttachment({ method: 'POST', body })
          current.files[0] = { ...current.files[0], attachment, failed: false }
        }
        uploading = undefined
        const reasoningReference = reasoning?.reference()
        // Another conversation may start saving while attachments are uploading.
        // Keep the uploaded draft until its account-level preference is ready.
        if (reasoning && !reasoningReference) return
        current.pending = messageSubmission(
          current,
          conversationId,
          personaId,
          execution?.selected,
          reasoningReference,
        )
        if (!directFile)
          setDraft(composerKey, (previous: Composer | undefined) =>
            updateSendingDraft(previous, composer.key, { pending: current.pending }),
          )
      }
      const sent = await sendMessage(current.pending.body, current.pending.key)
      activity?.accepted(sent)
      task?.accepted(sent)
      rememberConversation(sent.conversationId)
      if (directFile) finishDirectRecording(directFile, sent.conversationId)
      else {
        current.files.forEach((file) => URL.revokeObjectURL(file.url))
        setDraft(composerKey, (previous: Composer | undefined) =>
          updateSendingDraft(previous, composer.key, null),
        )
      }
      if (active.current) {
        refresh()
        onSent(sent.conversationId, current.pending.body.personaId ?? current.submissionPersonaId)
      }
      return true
    } catch (e) {
      if (uploading && !directFile) {
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
      if (
        !directFile &&
        e instanceof ApiError &&
        ([400, 403, 404, 413, 415, 422, 429].includes(e.status) ||
          [
            'conversation_busy',
            'execution_settings_changed',
            'reasoning_settings_changed',
          ].includes(e.code ?? ''))
      ) {
        setDraft(composerKey, (previous: Composer | undefined) =>
          updateSendingDraft(previous, composer.key, { pending: undefined }),
        )
      }
      if (
        directFile &&
        (!current.pending ||
          (e instanceof ApiError && [400, 403, 404, 413, 415, 422, 429].includes(e.status)))
      ) {
        for (const file of current.files)
          if (file.attachment) void deleteDraftAttachment(file.attachment.id).catch(() => {})
      }
      if (e instanceof ApiError && e.code === 'reasoning_settings_changed')
        void reasoning?.refresh()
      if (e instanceof ApiError && e.code === 'execution_settings_changed')
        void execution?.refresh()
      if (e instanceof ApiError && e.code === 'conversation_busy') void task?.refresh()
      if (!directFile && active.current && !isCancelled(e)) {
        if (e instanceof ApiError && [413, 415, 422].includes(e.status) && current.files.length)
          setLimitError(e.message)
        else setSendError(e instanceof Error ? e : '发送未完成')
      }
    } finally {
      activity?.finish()
      setDraft(composerKey, (previous: Composer | undefined) =>
        updateSendingDraft(previous, composer.key, { sending: false, uploading: undefined }),
      )
      interaction?.release('message')
      sendingRef.current = false
      if (active.current) setBusy(false)
    }
  }
  return {
    busy: busy || !!directSendingFile,
    sendingRef,
    send: async () => {
      await send()
    },
    directSendingFile,
  }
}
