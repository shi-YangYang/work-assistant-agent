import { ApiError } from '@web/api/client'
import { useEffect, useState } from 'react'

export function useRetryWait(error: unknown) {
  const retryAt = error instanceof ApiError ? error.retryAt : 0
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    if (!retryAt || retryAt <= Date.now()) return
    const timer = setInterval(() => {
      setNow(Date.now())
      if (Date.now() >= retryAt) clearInterval(timer)
    }, 1000)
    return () => clearInterval(timer)
  }, [retryAt])
  return retryAt && error instanceof ApiError
    ? Math.min(error.retryAfter ?? 0, Math.max(0, Math.ceil((retryAt - now) / 1000)))
    : 0
}
