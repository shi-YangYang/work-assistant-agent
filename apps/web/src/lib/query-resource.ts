export type QuerySnapshot<T> = { data: T | null; error: Error | string; loading: boolean }
export type QueryFailure = { status?: number; retryAt?: number; code?: string; category?: string }

// Explicit, in-memory resource ownership. This module never issues HTTP itself.
export class QueryResource<T> {
  private snapshot: QuerySnapshot<T> = { data: null, error: '', loading: false }
  private listeners = new Set<() => void>()
  private readers = 0
  private flight?: Promise<void>
  private controller?: AbortController
  private revision = 0
  private dirty = true
  private disposed = false
  private retryAt = 0
  private unavailable = false
  private idle?: ReturnType<typeof setTimeout>
  private release?: ReturnType<typeof setTimeout>

  constructor(
    private read: (signal: AbortSignal) => Promise<T>,
    private evict: () => void = () => {},
  ) {
    this.scheduleRelease()
  }

  getSnapshot = () => this.snapshot
  subscribe = (listener: () => void) => {
    clearTimeout(this.idle)
    clearTimeout(this.release)
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
      if (!this.listeners.size) {
        // React StrictMode's immediate re-subscription retains the same request.
        this.idle = setTimeout(() => {
          this.dirty = true
        }, 0)
        this.scheduleRelease()
      }
    }
  }
  private scheduleRelease() {
    clearTimeout(this.release)
    this.release = setTimeout(() => {
      if (!this.listeners.size && !this.readers) {
        this.dispose()
        this.evict()
      }
    }, 30000)
  }
  private update(value: QuerySnapshot<T>) {
    this.snapshot = value
    this.listeners.forEach((listener) => listener())
  }
  ensure = () => (this.dirty ? this.refresh() : (this.flight ?? Promise.resolve()))
  // A passive refresh joins the existing read. Only a real invalidation queues a follow-up.
  refresh = (): Promise<void> => {
    if (this.disposed || Date.now() < this.retryAt) return Promise.resolve()
    if (this.flight) return this.flight
    const controller = new AbortController()
    this.controller = controller
    const revision = this.revision
    this.dirty = false
    this.update({ ...this.snapshot, loading: true })
    this.flight = Promise.resolve()
      .then(() => this.read(controller.signal))
      .then(
        (data) => {
          if (this.disposed || controller.signal.aborted || revision !== this.revision) return
          this.retryAt = 0
          this.update({ data, error: '', loading: false })
        },
        (error: unknown) => {
          if (this.disposed || controller.signal.aborted || revision !== this.revision) return
          const failure = error as QueryFailure | null
          if (failure?.category === 'cancelled') return
          this.unavailable =
            !!failure &&
            ([401, 403, 404].includes(failure.status ?? 0) ||
              ['business_access_changed', 'source_changed'].includes(failure.code ?? ''))
          this.retryAt = failure?.retryAt ?? 0
          this.update({
            data: this.unavailable ? null : this.snapshot.data,
            error: error instanceof Error ? error : '连接失败',
            loading: false,
          })
        },
      )
      .finally(async () => {
        this.flight = undefined
        this.controller = undefined
        if (this.dirty && !this.disposed && this.listeners.size) await this.refresh()
      })
    return this.flight
  }
  invalidate = () => {
    if (this.disposed) return Promise.resolve()
    this.revision++
    this.dirty = true
    return this.listeners.size ? this.refresh() : Promise.resolve()
  }
  set = (data: T | ((current: T | null) => T)) => {
    if (this.disposed) return
    this.revision++
    this.dirty = false
    this.unavailable = false
    this.update({
      data:
        typeof data === 'function' ? (data as (current: T | null) => T)(this.snapshot.data) : data,
      error: '',
      loading: false,
    })
  }
  async get(signal?: AbortSignal, options?: { fresh?: boolean }) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    this.readers++
    clearTimeout(this.release)
    try {
      const request = options?.fresh ? this.refresh() : this.ensure()
      if (signal) {
        await new Promise<void>((resolve, reject) => {
          const abort = () => reject(new DOMException('Aborted', 'AbortError'))
          signal.addEventListener('abort', abort, { once: true })
          void request
            .then(resolve, reject)
            .finally(() => signal.removeEventListener('abort', abort))
        })
      } else await request
      if (signal?.aborted || this.disposed) throw new DOMException('Aborted', 'AbortError')
      if (this.snapshot.error) throw this.snapshot.error
      return this.snapshot.data as T
    } finally {
      this.readers--
      if (!this.readers && !this.listeners.size && !this.disposed) this.scheduleRelease()
    }
  }
  dispose = () => {
    this.disposed = true
    clearTimeout(this.idle)
    clearTimeout(this.release)
    this.controller?.abort()
    this.update({ data: null, error: '', loading: false })
  }
}

const resources = new Map<string, { dispose: () => void }>()
export function sharedResource<T extends { dispose: () => void }>(
  key: string,
  create: (evict: () => void) => T,
): T {
  let value = resources.get(key)
  if (!value) {
    value = create(() => {
      if (resources.get(key) === value) resources.delete(key)
    })
    resources.set(key, value)
  }
  return value as T
}
export function clearQueryResources() {
  const previous = [...resources.values()]
  resources.clear()
  previous.forEach((resource) => resource.dispose())
}
