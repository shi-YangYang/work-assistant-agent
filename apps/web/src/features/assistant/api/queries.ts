import type { Conversation } from '@paa/api-contracts'
import { api, epoch, queryIdentity } from '@web/api/client'
import { QueryResource, sharedResource } from '@web/lib/query-resource'

export function assistantQuery<T>(
  path: string | null,
  owner = queryIdentity,
  read?: (signal: AbortSignal) => Promise<T>,
) {
  if (!path) return null
  const key = JSON.stringify([epoch, owner, path])
  return sharedResource(
    key,
    (evict) => new QueryResource<T>(read ?? ((signal) => api<T>(path, { signal })), evict),
  )
}
export function saveConversationQuery(conversation: Conversation, owner = queryIdentity) {
  const resource = assistantQuery<Conversation>(`/conversations/${conversation.id}`, owner)!
  const current = resource.getSnapshot().data
  if (!current || conversation.revision >= current.revision) resource.set(conversation)
}
