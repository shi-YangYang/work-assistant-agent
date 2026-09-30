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
  private refreshPending = false
  private dirty = true
  private revision = 0
  private idle?: ReturnType<typeof setTimeout>
  private release?: ReturnType<typeof setTimeout>
  private controller: AbortController | null = null
  private listeners = new Set<() => void>()

  constructor(
    private path: string | null,
    private order: keyof T,
    private read: (path: string, options: RequestInit) => Promise<Page<T>> = api<Page<T>>,
    private evict?: () => void,
  ) {
    if (evict) this.scheduleRelease()
  }

  subscribe = (listener: () => void) => {
    clearTimeout(this.idle)
    clearTimeout(this.release)
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
      if (this.evict && !this.listeners.size) {
        this.idle = setTimeout(() => {
          this.dirty = true
        }, 0)
        this.scheduleRelease()
      }
    }
  }
  private scheduleRelease() {
    this.release = setTimeout(() => {
      if (!this.listeners.size) {
        this.dispose()
        this.evict?.()
      }
    }, 30000)
  }
  getSnapshot = () => this.snapshot
  private update(snapshot: Snapshot<T>) {
    this.snapshot = snapshot
    this.listeners.forEach((listener) => listener())
  }
  private boundary(item: T): Boundary {
    return [String(item[this.order]), item.id]
  }
  ensure = () => (this.dirty ? this.refresh() : Promise.resolve())
  refresh = async () => {
    if (this.evict) this.unavailable = false
    if (this.controller) {
      // Non-shared callers use refresh after writes and retain their queued follow-up.
      if (!this.evict) this.refreshPending = true
      return
    }
    return this.load(false)
  }
  invalidate = async () => {
    if (this.evict) this.unavailable = false
    this.revision++
    this.dirty = true
    if (this.controller) {
      this.refreshPending = true
      return
    }
    return this.load(false)
  }
  loadMore = () => this.load(true)
  dispose = () => {
    clearTimeout(this.idle)
    clearTimeout(this.release)
    this.refreshPending = false
    this.controller?.abort()
    this.controller = null
    if (this.evict) this.update({ data: null, error: '', loading: false })
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
    const revision = this.revision
    this.dirty = false
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
        if (controller.signal.aborted || revision !== this.revision) return
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
      if (controller.signal.aborted || revision !== this.revision || isCancelled(error)) return
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
      if (this.controller === controller) {
        this.controller = null
        if (this.refreshPending) {
          this.refreshPending = false
          void this.load(false)
        }
      }
    }
  }
}
