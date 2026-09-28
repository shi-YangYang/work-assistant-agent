import type {
  Attachment,
  DeliverableReference,
  ExecutionMode,
  BusinessAction,
  Conversation,
  ContextUsage,
  Job,
  Page,
  PersonaId,
  WorkMessage,
  Work,
  WorkReference,
} from '@paa/api-contracts'
import { api, write } from '@web/api/client'

export function resolveBusinessAction(
  current: BusinessAction,
  choice: 'confirm' | 'cancel',
  body: { expectedRevision: number },
) {
  return write<
    BusinessAction & { continuation?: { conversationId: string; messageId: string; jobId: string } }
  >(`/business-actions/${current.id}/${choice}`, body)
}

export function readAttachmentBytes(url: string | undefined, options: RequestInit) {
  return api<ArrayBuffer>((url ?? '').replace(/^\/api\/v1/, ''), options, 'bytes')
}

export function retryDocument(attachment: Attachment, body: Record<string, never>) {
  return write(`/uploads/${attachment.id}/retry`, body)
}

export function documentExtractionPath(
  attachmentId: string,
  start: number,
  revision: number | undefined,
) {
  return `/uploads/${attachmentId}/extraction?start=${start}${revision !== undefined ? `&revision=${revision}` : ''}`
}

export function correctTranscript(
  message: WorkMessage,
  body: { text: FormDataEntryValue | null; expectedRevision: number },
) {
  return write(`/messages/${message.id}/transcript`, body, 'PATCH')
}

export function resolveProgressDrafts(
  action: 'confirm' | 'ignore',
  body: { items: { id: string; expectedRevision: number }[] },
  key: string,
) {
  return write(`/progress-drafts/${action}`, body, 'POST', key)
}

export function conversationMessagesPath(conversationId: string | undefined) {
  return conversationId ? `/messages?conversationId=${conversationId}` : null
}

export function orphanActionsPath(conversationId: string | undefined) {
  return conversationId
    ? `/business-actions?conversationId=${conversationId}&orphanOnly=true`
    : null
}

export function uploadAttachment(options: RequestInit) {
  return api<Attachment>('/uploads', options)
}

export function sendMessage(
  body: {
    conversationId?: string
    newConversation?: boolean
    personaId?: PersonaId
    executionMode?: ExecutionMode
    fullAccessConfirmed?: boolean
    text: string
    attachmentIds: string[]
    voiceCommandAttachmentId?: string
    voiceCommandAttachmentIds?: string[]
    replyTo: string | null
    deliverableReference?: DeliverableReference
    workReference?: WorkReference
  },
  key: string,
) {
  return write<{ conversationId: string; messageId: string; jobId: string }>(
    '/messages',
    body,
    'POST',
    key,
  )
}

export function conversationsPath(search: string) {
  return `/conversations?q=${encodeURIComponent(search)}`
}

export function conversationPath(conversationId: string | undefined) {
  return conversationId ? `/conversations/${conversationId}` : null
}

export function readConversation(item: Conversation) {
  return api<Conversation>(`/conversations/${item.id}`)
}

export function readConversationDeletion(item: Conversation) {
  return api<{ retainedSources: number }>(`/conversations/${item.id}/deletion`)
}

export function readMoreConversations(
  search: string,
  nextCursor?: string | null,
  signal?: AbortSignal,
) {
  return api<Page<Conversation>>(
    `${conversationsPath(search)}${nextCursor ? `&cursor=${encodeURIComponent(nextCursor)}` : ''}`,
    { signal },
  )
}

export function renameConversation(
  editing: Conversation,
  body: { title: string; expectedRevision: number },
) {
  return write<Conversation>(`/conversations/${editing.id}`, body, 'PATCH')
}

export function updateConversationPersona(
  conversation: Conversation,
  body: { personaId: PersonaId; expectedRevision: number },
) {
  return write<Conversation>(`/conversations/${conversation.id}`, body, 'PATCH')
}

export function deleteConversation(deleting: Conversation, body: { expectedRevision: number }) {
  return write(`/conversations/${deleting.id}`, body, 'DELETE')
}

export function messagePath(id: string | undefined) {
  return `/messages/${id}`
}

export function readConversationForBreadcrumb(id: string, options: RequestInit) {
  return api<Conversation>(`/conversations/${id}`, options)
}

export function readMessageForBreadcrumb(id: string, options: RequestInit) {
  return api<WorkMessage>(`/messages/${id}`, options)
}

export function readConversationContext(conversationId: string, signal?: AbortSignal) {
  return api<{ contextUsage: ContextUsage | null }>(
    `/conversations/${conversationId}/context-usage`,
    { signal },
  )
}

export function readActiveAssistantJob(conversationId: string, signal?: AbortSignal) {
  return api<{ job: Job | null }>(`/conversations/${conversationId}/active-job`, { signal })
}

export function referenceWorksPath(query: string) {
  return `/work-items?q=${encodeURIComponent(query)}`
}

export function readReferenceWork(id: string, signal: AbortSignal) {
  return api<Work>(`/work-items/${encodeURIComponent(id)}`, { signal })
}
