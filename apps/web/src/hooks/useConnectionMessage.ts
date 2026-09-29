import { useEffect, useState } from 'react'

export function useConnectionMessage(enabled = true) {
  const [message, setMessage] = useState('')
  useEffect(() => {
    if (!enabled) return
    const offline = () => setMessage('网络可能已断开。输入仍保留，联网后会恢复当前页面数据。')
    const failure = (event: Event) => setMessage((event as CustomEvent<string>).detail)
    const connected = () => setMessage('')
    if (navigator.onLine === false) offline()
    window.addEventListener('offline', offline)
    window.addEventListener('online', connected)
    window.addEventListener('paa-connection-error', failure)
    window.addEventListener('paa-request-connected', connected)
    return () => {
      window.removeEventListener('offline', offline)
      window.removeEventListener('online', connected)
      window.removeEventListener('paa-connection-error', failure)
      window.removeEventListener('paa-request-connected', connected)
    }
  }, [enabled])
  return message
}
