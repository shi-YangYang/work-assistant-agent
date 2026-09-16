import type { Identity } from '@paa/api-contracts'
import type { Composer } from './audio-capture'
import type { DraftStore } from './workspace'

export const identityScope = (identity: Identity) =>
  `${identity.company.id}:${identity.member.id}:${identity.member.role}`
function release(drafts: DraftStore) {
  for (const [key, value] of Object.entries(drafts)) {
    if (key.startsWith('composer:'))
      (value as Composer).files.forEach((file) => URL.revokeObjectURL(file.url))
  }
}
// Page-memory only. Writers are bound to one verified session, so delayed
// uploads/recording callbacks cannot reintroduce drafts after logout or expiry.
export class SessionDrafts {
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
    if (this.scope !== scope || identity.member.mustChangePassword) this.clear()
    this.scope = scope
    this.generation++
  }
  suspend() {
    this.generation++
    this.drafts = Object.fromEntries(
      Object.entries(this.drafts)
        .filter(([key]) => key.startsWith('composer:'))
        .map(([key, value]) => [
          key,
          { ...(value as Composer), sending: false, uploading: undefined },
        ]),
    )
    this.publish()
  }
  clear() {
    this.generation++
    release(this.drafts)
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
