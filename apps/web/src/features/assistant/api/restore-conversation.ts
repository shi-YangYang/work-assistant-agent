import type { Conversation, Page } from '@paa/api-contracts'
import { assistantQuery } from './queries'
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

export function restoreConversation(
  remembered: string | null,
  signal: AbortSignal,
  owner?: string,
  options?: { fresh?: boolean },
) {
  return resumeConversation(remembered, <T>(path: string) =>
    assistantQuery<T>(path, owner)!.get(signal, options),
  )
}

export async function latestChat(
  signal: AbortSignal,
  owner?: string,
  options?: { fresh?: boolean },
) {
  const page = await assistantQuery<Page<Conversation>>(
    '/conversations?order=last_message',
    owner,
  )!.get(signal, options)
  return page.items[0]?.id ?? null
}
