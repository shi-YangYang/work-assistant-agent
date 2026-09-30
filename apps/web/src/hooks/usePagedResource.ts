import { epoch } from '@web/api/client'
import { sharedResource } from '@web/lib/query-resource'
import { PagedResource } from '@web/lib/paged-resource'
import { useEffect, useMemo, useSyncExternalStore } from 'react'

export function usePagedResource<T extends { id: string }>(
  path: string | null,
  order: keyof T,
  interval = 0,
  options?: { scope: string },
) {
  const scope = options?.scope
  const generation = epoch
  const resource = useMemo(
    () =>
      scope === undefined || !path
        ? new PagedResource<T>(path, order)
        : sharedResource(
            JSON.stringify(['pages', generation, scope, path, order]),
            (evict) => new PagedResource<T>(path, order, undefined, evict),
          ),
    [path, order, scope, generation],
  )
  const snapshot = useSyncExternalStore(resource.subscribe, resource.getSnapshot)
  useEffect(() => {
    if (!path) return
    if (scope !== undefined) {
      void resource.ensure()
      return
    }
    const refresh = () => void resource.refresh()
    const invalidate = () => void resource.invalidate()
    const visibleRefresh = () => {
      if (!document.hidden) refresh()
    }
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      await resource.refresh()
      if (!disposed && interval > 0)
        timer = setTimeout(poll, document.hidden ? Math.max(interval, 30000) : interval)
    }
    void poll()
    window.addEventListener('paa-record-updated', invalidate)
    window.addEventListener('focus', refresh)
    window.addEventListener('online', visibleRefresh)
    const visible = () => {
      if (!document.hidden) refresh()
    }
    document.addEventListener('visibilitychange', visible)
    return () => {
      disposed = true
      clearTimeout(timer)
      window.removeEventListener('paa-record-updated', invalidate)
      window.removeEventListener('focus', refresh)
      window.removeEventListener('online', visibleRefresh)
      document.removeEventListener('visibilitychange', visible)
      resource.dispose()
    }
  }, [resource, interval, path, scope])
  return {
    ...snapshot,
    refresh: resource.refresh,
    invalidate: resource.invalidate,
    loadMore: resource.loadMore,
  }
}
