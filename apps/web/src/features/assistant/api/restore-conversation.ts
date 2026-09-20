import type { Conversation, Page } from '@paa/api-contracts'
import { api, ApiError } from '@web/api/client'

export async function resumeConversation(
  remembered: string | null,
  read: <T>(path: string) => Promise<T> = api,
) {
  if (remembered) {
    try {
      return (await read<Conversation>(`/conversations/${encodeURIComponent(remembered)}`)).id
    } catch (error) {
      if (!(error instanceof ApiError) || ![403, 404].includes(error.status)) throw error
    }
  }
  return (await read<Page<Conversation>>('/conversations')).items[0]?.id ?? null
}

export function restoreConversation(remembered: string | null, signal: AbortSignal) {
  return resumeConversation(remembered, (path) => api(path, { signal }))
}
