import type { KeyboardEvent } from 'react'

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
