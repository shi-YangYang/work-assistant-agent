import type { KeyboardEvent } from 'react'
import type { Conversation, Page } from '@paa/api-contracts'
import { ApiError } from './api'

export async function resumeConversation(
  remembered: string | null,
  read: <T>(path: string) => Promise<T>,
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

export function submitOnEnter(event: KeyboardEvent<HTMLTextAreaElement>, send: () => void) {
  if (
    event.key !== 'Enter' ||
    event.shiftKey ||
    event.nativeEvent.isComposing ||
    event.nativeEvent.keyCode === 229
  )
    return
  event.preventDefault()
  if (!event.repeat) send()
}
