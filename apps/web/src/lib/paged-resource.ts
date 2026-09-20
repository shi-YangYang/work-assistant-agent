import type { Page } from '@paa/api-contracts'
import { api, ApiError, isCancelled } from '@web/api/client'

type Boundary = [string, string]

type Snapshot<T> = { data: Page<T> | null; error: Error | string; loading: boolean }

// Keep the oldest explicitly expanded boundary, not a cache of old rows. Each
// read walks fresh cursors, so deleting an old row (including a cursor) cannot
// leave its body visible indefinitely or strand pagination at a deleted anchor.
export class PagedResource<T extends { id: string }> {
  private snapshot: Snapshot<T> = { data: null, error: '', loading: false }
  private through: Boundary | null = null
  private retryAt = 0
  private unavailable = false
  private controller: AbortController | null = null
  private listeners = new Set<() => void>()

  constructor(
    private path: string | null,
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
    if (
      !this.path ||
      this.unavailable ||
      Date.now() < this.retryAt ||
      this.controller ||
      (extend && !this.snapshot.data?.nextCursor)
    )
      return
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
      this.retryAt = 0
      this.update({ data, error: '', loading: false })
    } catch (error) {
      if (controller.signal.aborted || isCancelled(error)) return
      const unavailable = error instanceof ApiError && [403, 404].includes(error.status)
      if (unavailable) {
        this.through = null
        this.unavailable = true
      }
      if (error instanceof ApiError && error.status === 429)
        this.retryAt = error.retryAt || Date.now() + 5000
      this.update({
        data: unavailable ? null : this.snapshot.data,
        error: error instanceof Error ? error : '连接失败',
        loading: false,
      })
    } finally {
      if (this.controller === controller) this.controller = null
    }
  }
}
