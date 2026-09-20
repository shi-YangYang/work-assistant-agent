import { PagedResource } from '@web/lib/paged-resource'
import { useEffect, useMemo, useSyncExternalStore } from 'react'

export function usePagedResource<T extends { id: string }>(
  path: string | null,
  order: keyof T,
  interval: number,
) {
  const resource = useMemo(() => new PagedResource<T>(path, order), [path, order])
  const snapshot = useSyncExternalStore(resource.subscribe, resource.getSnapshot)
  useEffect(() => {
    if (!path) return
    const refresh = () => void resource.refresh()
    const visibleRefresh = () => {
      if (!document.hidden) refresh()
    }
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      await resource.refresh()
      if (!disposed)
        timer = setTimeout(poll, document.hidden ? Math.max(interval, 30000) : interval)
    }
    void poll()
    window.addEventListener('paa-record-updated', refresh)
    window.addEventListener('focus', refresh)
    window.addEventListener('online', visibleRefresh)
    const visible = () => {
      if (!document.hidden) refresh()
    }
    document.addEventListener('visibilitychange', visible)
    return () => {
      disposed = true
      clearTimeout(timer)
      window.removeEventListener('paa-record-updated', refresh)
      window.removeEventListener('focus', refresh)
      window.removeEventListener('online', visibleRefresh)
      document.removeEventListener('visibilitychange', visible)
      resource.dispose()
    }
  }, [resource, interval, path])
  return { ...snapshot, refresh: resource.refresh, loadMore: resource.loadMore }
}
