import { useEffect, useRef } from 'react'

export type RegisterConversationRefresh = (refresh: () => void) => () => void

// One recovery round for this mounted conversation; window focus is deliberately ignored.
export function useConversationRefresh(
  conversationId: string | undefined,
  refresh: () => void,
  register?: RegisterConversationRefresh,
) {
  const callback = useRef(refresh)
  useEffect(() => {
    callback.current = refresh
  }, [refresh])
  useEffect(() => {
    if (!conversationId) return
    if (register) return register(() => callback.current())
    let queued = false
    let active = true
    let previous = -Infinity
    const recover = () => {
      if (document.hidden || navigator.onLine === false || queued || Date.now() - previous < 100)
        return
      queued = true
      queueMicrotask(() => {
        queued = false
        if (active && !document.hidden && navigator.onLine !== false) {
          previous = Date.now()
          callback.current()
        }
      })
    }
    const disconnected = () => {
      previous = -Infinity
    }
    window.addEventListener('online', recover)
    window.addEventListener('offline', disconnected)
    document.addEventListener('visibilitychange', recover)
    return () => {
      active = false
      window.removeEventListener('online', recover)
      window.removeEventListener('offline', disconnected)
      document.removeEventListener('visibilitychange', recover)
    }
  }, [conversationId, register])
}
