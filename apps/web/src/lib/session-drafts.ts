import type { Identity } from '@paa/api-contracts'
import type { DraftStore } from '@web/lib/workspace'

export const identityScope = (identity: Identity) =>
  `${identity.company.id}:${identity.member.id}:${identity.member.role}`

export interface DraftLifecycle {
  suspend: (drafts: DraftStore) => DraftStore
  release: (drafts: DraftStore) => void
}

// Page-memory only. Writers are bound to one verified session, so delayed
// uploads/recording callbacks cannot reintroduce drafts after logout or expiry.
export class SessionDrafts {
  constructor(private lifecycle: DraftLifecycle) {}
  private scope: string | null = null
  private generation = 0
  private drafts: DraftStore = {}
  private listeners = new Set<() => void>()
  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }
  getSnapshot = () => this.drafts
  private publish() {
    this.listeners.forEach((listener) => listener())
  }
  resume(identity: Identity) {
    const scope = identityScope(identity)
    if (this.scope !== scope) this.clear()
    this.scope = scope
    this.generation++
  }
  suspend() {
    this.generation++
    this.drafts = this.lifecycle.suspend(this.drafts)
    this.publish()
  }
  clear() {
    this.generation++
    this.lifecycle.release(this.drafts)
    this.drafts = {}
    this.scope = null
    this.publish()
  }
  get version() {
    return this.generation
  }
  writer(generation = this.generation) {
    return (key: string, value: unknown) => {
      if (generation !== this.generation) return
      const resolved = typeof value === 'function' ? value(this.drafts[key]) : value
      const next = { ...this.drafts }
      if (resolved === undefined) delete next[key]
      else next[key] = resolved
      this.drafts = next
      this.publish()
    }
  }
}
