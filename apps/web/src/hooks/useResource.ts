import { api, ApiError, epoch, isCancelled } from '@web/api/client'
import { useCallback, useEffect, useRef, useState } from 'react'

export function useResource<T>(
  path: string | null,
  interval = 0,
  shouldPoll?: (data: T) => boolean,
) {
  const sessionEpoch = epoch
  const [loaded, setLoaded] = useState<{ path: string; epoch: number; data: T } | null>(null)
  const [failure, setFailure] = useState<{
    path: string
    epoch: number
    error: Error | string
  } | null>(null)
  const [revision, setRevision] = useState(0)
  const retry = useRef({ path, epoch, at: 0 })
  const refresh = useCallback(() => setRevision((n) => n + 1), [])
  useEffect(() => {
    if (retry.current.path !== path || retry.current.epoch !== epoch)
      retry.current = { path, epoch, at: 0 }
    if (!path) return
    const waiting = retry.current
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    let loading = false
    let unavailable = false
    let polling = !!interval
    const load = async () => {
      if (loading || controller.signal.aborted || unavailable) return
      if (waiting.epoch !== epoch) {
        waiting.epoch = epoch
        waiting.at = 0
      }
      const remaining = waiting.at - Date.now()
      if (remaining > 0) {
        clearTimeout(timer)
        timer = setTimeout(load, remaining)
        return
      }
      loading = true
      let nextDelay = interval
      clearTimeout(timer)
      try {
        const result = await api<T>(path, { signal: controller.signal })
        if (!controller.signal.aborted) {
          waiting.at = 0
          setLoaded({ path, epoch: sessionEpoch, data: result })
          setFailure(null)
          polling = !!interval && (!shouldPoll || shouldPoll(result))
        }
      } catch (e) {
        if (!controller.signal.aborted && !isCancelled(e)) {
          setFailure({ path, epoch: sessionEpoch, error: e instanceof Error ? e : '连接失败' })
          if (e instanceof ApiError && e.status === 429) {
            waiting.at = e.retryAt || Date.now() + 5000
            nextDelay = Math.max(interval, waiting.at - Date.now())
          }
          if (
            e instanceof ApiError &&
            ([401, 403, 404].includes(e.status) ||
              e.code === 'business_access_changed' ||
              e.code === 'source_changed')
          ) {
            setLoaded(null)
            unavailable = true
          }
        }
      } finally {
        loading = false
      }
      if (polling && !controller.signal.aborted && !unavailable)
        timer = setTimeout(load, document.hidden ? Math.max(nextDelay, 30000) : nextDelay)
    }
    const recover = () => {
      if (!document.hidden) void load()
    }
    void load()
    window.addEventListener('online', recover)
    document.addEventListener('visibilitychange', recover)
    return () => {
      controller.abort()
      clearTimeout(timer)
      window.removeEventListener('online', recover)
      document.removeEventListener('visibilitychange', recover)
    }
  }, [path, interval, shouldPoll, revision, sessionEpoch])
  return {
    data: loaded?.path === path && loaded.epoch === sessionEpoch ? loaded.data : null,
    error: failure?.path === path && failure.epoch === sessionEpoch ? failure.error : '',
    refresh,
  }
}
