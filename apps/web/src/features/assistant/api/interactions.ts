import type { AssistantInteraction, Conversation, ExecutionMode } from '@paa/api-contracts'
import { write } from '@web/api/client'

export function conversationInteractionsPath(conversationId?: string) {
  return conversationId ? `/conversations/${conversationId}/interactions` : null
}

export function updateExecutionMode(
  conversation: Conversation,
  executionMode: ExecutionMode,
  fullAccessConfirmed: boolean,
) {
  return write<Conversation>(
    `/conversations/${conversation.id}`,
    {
      executionMode,
      fullAccessConfirmed,
      expectedRevision: conversation.revision,
    },
    'PATCH',
  )
}

export type TaskContinuation = { conversationId: string; messageId: string; jobId: string }
export type InteractionAnswer = AssistantInteraction['answers'][number]
export function answerInteraction(
  interaction: AssistantInteraction,
  answers: InteractionAnswer[],
  key: string,
) {
  return write<{ interaction: AssistantInteraction; continuation?: TaskContinuation }>(
    `/interactions/${interaction.id}/answer`,
    { expectedRevision: interaction.revision, answers },
    'POST',
    key,
  )
}
export function cancelInteraction(interaction: AssistantInteraction, key: string) {
  return write<{ interaction: AssistantInteraction; continuation?: TaskContinuation }>(
    `/interactions/${interaction.id}/cancel`,
    { expectedRevision: interaction.revision },
    'POST',
    key,
  )
}
