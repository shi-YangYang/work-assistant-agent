import type { ExecutionMode, PersonaId, ReasoningReference } from '@paa/api-contracts'
import type { Composer } from '@web/features/assistant/lib/audio-capture'
export * from '@web/utils/attachments'

export function updateSendingDraft(
  previous: Composer | undefined,
  key: string,
  update: Partial<Composer> | null,
) {
  if (previous?.key !== key) return previous
  return update === null ? undefined : { ...previous, ...update }
}

export function messageSubmission(
  composer: Composer,
  conversationId?: string,
  personaId?: PersonaId,
  executionMode?: ExecutionMode,
  reasoning?: ReasoningReference,
): NonNullable<Composer['pending']> {
  if (composer.pending) return composer.pending
  return {
    key: composer.key,
    body: {
      conversationId,
      personaId: composer.submissionPersonaId ?? personaId,
      ...(!conversationId ? { newConversation: true } : {}),
      ...(executionMode ? { executionMode } : {}),
      ...(reasoning ? { reasoning } : {}),
      text: composer.text,
      attachmentIds: composer.files.map((file) => {
        if (!file.attachment) throw new Error('附件尚未上传完成')
        return file.attachment.id
      }),
      ...(composer.files.some((file) => file.recorded && file.attachment?.kind === 'audio')
        ? {
            voiceCommandAttachmentIds: composer.files
              .filter((file) => file.recorded && file.attachment?.kind === 'audio')
              .map((file) => file.attachment!.id),
          }
        : {}),
      replyTo: composer.replyTo ?? null,
      ...(composer.workReference
        ? { workReference: { workId: composer.workReference.workId } }
        : {}),
      ...(composer.deliverableReference
        ? { deliverableReference: structuredClone(composer.deliverableReference) }
        : {}),
    },
  }
}
