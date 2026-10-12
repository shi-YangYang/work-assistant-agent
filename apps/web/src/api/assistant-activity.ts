import type { AssistantActivity, AssistantActivityJob, Job, JobFeedback } from '@paa/api-contracts'
import { api, epoch, isCancelled } from '@web/api/client'
import {
  feedbackDisconnected,
  reconnectJobFeedback,
  subscribeJobFeedback,
} from '@web/api/job-feedback'

export type AssistantActivityState = 'idle' | 'working' | 'unknown'
export type AcceptedAssistantTask = { conversationId: string; messageId: string; jobId: string }
const running = (state: string) => state === 'queued' || state === 'running'
export const assistantActivityKey = (owner: string, conversation: string) =>
  `paa-assistant-task:${owner}:${conversation}`

const announcements = new Set<string>()
export function announceAssistantActivity(owner: string, conversation: string | null) {
  const key = assistantActivityKey(owner, conversation ?? 'legacy')
  const generation = epoch
  const pending = `${generation}:${key}`
  if (announcements.has(pending)) return
  announcements.add(pending)
  queueMicrotask(() => {
    announcements.delete(pending)
    if (epoch !== generation) return
    try {
      localStorage.setItem(key, crypto.randomUUID())
    } catch {
      // Explicit visibility/online synchronization also works without storage.
    }
  })
}

type Entry = {
  job: AssistantActivityJob
  revision: number
  unknown: boolean
  release?: () => void
}
function newer(current: AssistantActivityJob, next: AssistantActivityJob) {
  if (current.attempt === next.attempt && !running(current.state) && running(next.state))
    return false
  for (const key of ['attempt', 'fence', 'seq'] as const) {
    if (next[key] !== current[key]) return next[key] > current[key]
  }
  return next.updatedAt >= current.updatedAt
}

// Only scalar task state is retained here. Reply text/tokens never enter the
// application snapshot or cause the Shell to render again.
export class AssistantActivityStore {
  private jobs = new Map<string, Entry>()
  private ended = new Map<string, AssistantActivityJob>()
  private unavailable = new Map<string, number>()
  private sending = new Set<symbol>()
  private listeners = new Set<() => void>()
  private revision = 0
  private state: AssistantActivityState = 'idle'
  private disposed = false
  private request?: AbortController
  private scheduled = false
  private queuedRefresh = false
  readonly generation: number
  constructor(
    readonly owner: string,
    generation = epoch,
  ) {
    this.generation = generation
  }
  private valid = () => !this.disposed && this.generation === epoch
  getSnapshot = (): AssistantActivityState => (this.valid() ? this.state : 'idle')
  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }
  private publish() {
    const entries = [...this.jobs.values()]
    const next =
      this.sending.size || entries.some((item) => !item.unknown)
        ? 'working'
        : entries.length
          ? 'unknown'
          : 'idle'
    if (this.state === next) return
    this.state = next
    this.listeners.forEach((listener) => listener())
  }
  private remove(id: string, terminal?: AssistantActivityJob) {
    const current = this.jobs.get(id)
    current?.release?.()
    this.jobs.delete(id)
    if (terminal) this.ended.set(id, terminal)
  }
  private merge(job: AssistantActivityJob, notify = false) {
    if (!this.valid()) return
    const current = this.jobs.get(job.id)
    const previous = current?.job ?? this.ended.get(job.id)
    if (previous && !newer(previous, job)) return
    this.unavailable.delete(job.id)
    if (!running(job.state)) {
      this.remove(job.id, job)
      this.revision++
      if (notify && current) announceAssistantActivity(this.owner, job.conversationId)
      return
    }
    this.ended.delete(job.id)
    const entry: Entry = current ?? { job, revision: 0, unknown: false }
    const restart =
      !current || current.job.attempt !== job.attempt || current.job.fence !== job.fence
    entry.job = job
    entry.unknown = navigator.onLine === false
    entry.revision = ++this.revision
    this.jobs.set(job.id, entry)
    if (!restart) return
    entry.release?.()
    const release = subscribeJobFeedback(
      job.id,
      job.state,
      job.attempt,
      job.fence,
      (feedback) => {
        if (!this.valid() || this.jobs.get(job.id) !== entry) return
        if (!feedback) {
          // The shared transport only clears its value on authenticated
          // unavailability; a network disconnect uses the error callback.
          this.unavailable.set(job.id, ++this.revision)
          this.remove(job.id)
        } else {
          const incoming = this.fromFeedback(entry.job, feedback)
          if (!newer(entry.job, incoming)) return
          if (!running(incoming.state)) this.merge(incoming, true)
          else {
            entry.job = incoming
            entry.unknown = false
            entry.revision = ++this.revision
          }
        }
        this.publish()
      },
      (error) => {
        if (!this.valid() || this.jobs.get(job.id) !== entry || !error) return
        if (error === feedbackDisconnected || !error.startsWith('实时预览暂不可用')) {
          entry.unknown = true
          entry.revision = ++this.revision
          this.publish()
        }
      },
      () => {},
    )
    if (this.jobs.get(job.id) === entry) entry.release = release
    else release?.()
  }
  private fromFeedback(job: AssistantActivityJob, feedback: JobFeedback): AssistantActivityJob {
    const { attempt, fence, seq, state, stage, updatedAt } = feedback
    return { ...job, attempt, fence, seq, state, stage, updatedAt }
  }
  settle(job: Job) {
    if (!this.valid() || job.kind !== 'message' || running(job.state)) return
    const current = this.jobs.get(job.id)?.job
    if (!current) return
    const attempt = job.attempt ?? 0
    const fence = job.fence ?? 0
    // Persisted message history may confirm completion before the final SSE.
    // The Job DTO has no seq; retain it only for the same execution version.
    this.merge(
      {
        ...current,
        state: job.state,
        stage: job.stage ?? current.stage,
        attempt,
        fence,
        seq: attempt === current.attempt && fence === current.fence ? current.seq : 0,
        updatedAt: job.updatedAt,
      },
      true,
    )
    this.publish()
  }
  accept(receipt: AcceptedAssistantTask, value?: Job) {
    if (!this.valid()) return
    const previous = this.jobs.get(receipt.jobId)?.job
    const seq =
      value && previous && previous.attempt === value.attempt && previous.fence === value.fence
        ? previous.seq
        : 0
    this.merge({
      id: receipt.jobId,
      targetId: receipt.messageId,
      conversationId: receipt.conversationId,
      state: value?.state ?? 'queued',
      stage: value?.stage ?? 'queued',
      attempt: value?.attempt ?? 0,
      fence: value?.fence ?? 0,
      seq,
      updatedAt: value?.updatedAt ?? new Date().toISOString(),
    })
    this.publish()
    announceAssistantActivity(this.owner, receipt.conversationId)
  }
  begin() {
    const token = Symbol('assistant-send')
    if (this.valid()) {
      this.sending.add(token)
      this.publish()
    }
    return {
      accepted: (receipt: AcceptedAssistantTask, job?: Job) => {
        if (!this.valid()) return
        // Remove the temporary entry only in the same synchronous transaction
        // as registering the accepted job; observers never see an idle gap.
        this.sending.delete(token)
        this.accept(receipt, job)
      },
      finish: () => {
        if (this.valid() && this.sending.delete(token)) this.publish()
      },
    }
  }
  synchronize = () => {
    if (!this.valid() || this.scheduled || navigator.onLine === false) return
    if (this.request) {
      if (this.request.signal.aborted) this.queuedRefresh = true
      return
    }
    this.scheduled = true
    queueMicrotask(() => {
      this.scheduled = false
      if (this.valid()) void this.load()
    })
  }
  changed = () => {
    if (this.request) this.queuedRefresh = true
    else this.synchronize()
  }
  private async load() {
    const controller = new AbortController()
    this.request = controller
    const revision = this.revision
    try {
      const result = await api<AssistantActivity>('/assistant/activity', {
        signal: controller.signal,
      })
      if (!this.valid() || controller.signal.aborted) return
      const present = new Set(result.jobs.map((job) => job.id))
      const confirmed = new Map<string, AssistantActivityJob>()
      for (const job of result.jobs) {
        const changed = this.jobs.get(job.id)?.revision ?? this.unavailable.get(job.id) ?? 0
        if (changed <= revision) {
          this.merge(job)
          confirmed.set(job.id, job)
        }
      }
      for (const [id, entry] of this.jobs) {
        if (!present.has(id) && entry.revision <= revision) this.remove(id)
      }
      this.publish()
      // Shared recovery coalesces with the message area's recovery. Healthy
      // connections are left alone; no second stream or background timer.
      for (const id of this.jobs.keys()) void reconnectJobFeedback(id, confirmed.get(id))
    } catch (error) {
      if (!this.valid() || controller.signal.aborted || isCancelled(error)) return
      for (const entry of this.jobs.values()) {
        if (entry.revision <= revision) entry.unknown = true
      }
      this.publish()
    } finally {
      if (this.request === controller) this.request = undefined
      if (this.queuedRefresh) {
        this.queuedRefresh = false
        this.synchronize()
      }
    }
  }
  offline = () => {
    this.request?.abort()
    for (const entry of this.jobs.values()) {
      entry.unknown = true
      entry.revision = ++this.revision
    }
    this.publish()
  }
  activate = () => {
    this.disposed = false
  }
  dispose = () => {
    this.disposed = true
    this.request?.abort()
    for (const id of this.jobs.keys()) this.remove(id)
    this.sending.clear()
    this.state = 'idle'
    this.listeners.forEach((listener) => listener())
  }
}

let active: AssistantActivityStore | undefined
export function mountAssistantActivity(store: AssistantActivityStore) {
  active?.dispose()
  active = store
  store.activate()
  const visible = () => {
    if (!document.hidden) store.synchronize()
  }
  const storage = (event: StorageEvent) => {
    if (event.key?.startsWith(`paa-assistant-task:${store.owner}:`)) store.changed()
  }
  const expired = () => store.dispose()
  window.addEventListener('online', store.synchronize)
  window.addEventListener('offline', store.offline)
  window.addEventListener('storage', storage)
  window.addEventListener('paa-session-expired', expired)
  document.addEventListener('visibilitychange', visible)
  store.synchronize()
  return () => {
    window.removeEventListener('online', store.synchronize)
    window.removeEventListener('offline', store.offline)
    window.removeEventListener('storage', storage)
    window.removeEventListener('paa-session-expired', expired)
    document.removeEventListener('visibilitychange', visible)
    store.dispose()
    if (active === store) active = undefined
  }
}
export function beginAssistantActivity(owner: string) {
  return active?.owner === owner ? active.begin() : undefined
}
export function acceptAssistantActivity(owner: string, receipt: AcceptedAssistantTask, job?: Job) {
  if (active?.owner === owner) active.accept(receipt, job)
}
export function settleAssistantActivity(job: Job) {
  active?.settle(job)
}
