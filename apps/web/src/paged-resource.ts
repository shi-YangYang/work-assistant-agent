import { useEffect, useMemo, useSyncExternalStore } from 'react'
import type { Page } from '@paa/api-contracts'
import { api, ApiError } from './api'

type Boundary = [string, string]
type Snapshot<T> = { data: Page<T> | null; error: string; loading: boolean }

// Keep the oldest explicitly expanded boundary, not a cache of old rows. Each
// read walks fresh cursors, so deleting an old row (including a cursor) cannot
// leave its body visible indefinitely or strand pagination at a deleted anchor.
export class PagedResource<T extends { id: string }> {
  private snapshot: Snapshot<T> = { data: null, error: '', loading: false }
  private through: Boundary | null = null
  private controller: AbortController | null = null
  private listeners = new Set<() => void>()

  constructor(
    private path: string,
    private order: keyof T,
    private read: (path: string, options: RequestInit) => Promise<Page<T>> = api<Page<T>>,
  ) {}

  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }
  getSnapshot = () => this.snapshot
  private update(snapshot: Snapshot<T>) {
    this.snapshot = snapshot
    this.listeners.forEach((listener) => listener())
  }
  private boundary(item: T): Boundary {
    return [String(item[this.order]), item.id]
  }
  refresh = () => this.load(false)
  loadMore = () => this.load(true)
  dispose = () => {
    this.controller?.abort()
    this.controller = null
  }

  private async load(extend: boolean) {
    if (this.controller || (extend && !this.snapshot.data?.nextCursor)) return
    const controller = new AbortController()
    this.controller = controller
    this.update({ ...this.snapshot, loading: true })
    const previous = this.snapshot.data?.items.at(-1)
    const through = extend && previous ? this.boundary(previous) : this.through
    let extra = extend
    try {
      const items = new Map<string, T>()
      let cursor: string | null = null
      do {
        const page = await this.read(
          this.path +
            (cursor
              ? `${this.path.includes('?') ? '&' : '?'}cursor=${encodeURIComponent(cursor)}`
              : ''),
          { signal: controller.signal },
        )
        if (controller.signal.aborted) return
        page.items.forEach((item) => items.set(item.id, item))
        cursor = page.nextCursor ?? null
        const last = page.items.at(-1)
        const boundary = last ? this.boundary(last) : null
        const covered =
          !through ||
          (boundary &&
            (boundary[0] < through[0] || (boundary[0] === through[0] && boundary[1] <= through[1])))
        if (covered) {
          if (!extra) break
          extra = false
        }
      } while (cursor)
      const data = { items: [...items.values()], nextCursor: cursor }
      if (extend && data.items.length) this.through = this.boundary(data.items.at(-1)!)
      this.update({ data, error: '', loading: false })
    } catch (error) {
      if (controller.signal.aborted) return
      const unavailable = error instanceof ApiError && [403, 404].includes(error.status)
      if (unavailable) this.through = null
      this.update({
        data: unavailable ? null : this.snapshot.data,
        error: error instanceof Error ? error.message : '连接失败',
        loading: false,
      })
    } finally {
      if (this.controller === controller) this.controller = null
    }
  }
}

export function usePagedResource<T extends { id: string }>(
  path: string,
  order: keyof T,
  interval: number,
) {
  const resource = useMemo(() => new PagedResource<T>(path, order), [path, order])
  const snapshot = useSyncExternalStore(resource.subscribe, resource.getSnapshot)
  useEffect(() => {
    const refresh = () => void resource.refresh()
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
    const visible = () => {
      if (!document.hidden) refresh()
    }
    document.addEventListener('visibilitychange', visible)
    return () => {
      disposed = true
      clearTimeout(timer)
      window.removeEventListener('paa-record-updated', refresh)
      window.removeEventListener('focus', refresh)
      document.removeEventListener('visibilitychange', visible)
      resource.dispose()
    }
  }, [resource, interval])
  return { ...snapshot, refresh: resource.refresh, loadMore: resource.loadMore }
}
