import type { ReasoningSettings, ReasoningReference } from '@paa/api-contracts'
import { ApiError, epoch, isCancelled } from '@web/api/client'
import { useQueryResource } from '@web/hooks/useQueryResource'
import { QueryResource } from '@web/lib/query-resource'
import { identityScope } from '@web/lib/session-drafts'
import { useWorkspace } from '@web/lib/workspace'
import { useSyncExternalStore } from 'react'
import { assistantQuery } from '../api/queries'
import { reasoningSettingsPath, updateReasoningEffort } from '../api/reasoning'
import { useConversationRefresh } from './useConversationRefresh'

// Shared mutation state prevents a conversation switch from sending an old preference
// while its account-level save is still in flight.
class ReasoningMutation {
  private value: { saving: boolean; error: Error | string } = { saving: false, error: '' }
  private listeners = new Set<() => void>()
  private disposed = false
  constructor(
    private resource: QueryResource<ReasoningSettings>,
    private generation: number,
  ) {}
  getSnapshot = () => this.value
  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }
  private set(value: typeof this.value) {
    if (this.disposed) return
    this.value = value
    this.listeners.forEach((listener) => listener())
  }
  dispose = () => {
    this.disposed = true
    this.listeners.clear()
  }
  choose = async (effort: string) => {
    const current = this.resource.getSnapshot().data
    if (this.value.saving || !current) return
    this.set({ saving: true, error: '' })
    try {
      const result = await updateReasoningEffort(current, effort)
      if (!this.disposed && epoch === this.generation) {
        const latest = this.resource.getSnapshot().data
        // A newer read (including another tab's save) must win over a delayed PATCH.
        if (
          !latest ||
          (latest.configVersion === current.configVersion &&
            latest.preferenceRevision <= result.preferenceRevision)
        )
          this.resource.set(result)
      }
    } catch (error) {
      if (this.disposed || epoch !== this.generation || isCancelled(error)) return
      this.set({ saving: true, error: error as Error })
      if (error instanceof ApiError && error.code === 'reasoning_settings_changed')
        await this.resource.invalidate()
    } finally {
      this.set({ ...this.value, saving: false })
    }
  }
  refresh = async () => {
    await this.resource.invalidate()
    if (!this.resource.getSnapshot().error) this.set({ ...this.value, error: '' })
  }
}

const mutations = new WeakMap<QueryResource<ReasoningSettings>, ReasoningMutation>()

export function useReasoningEffort() {
  const { identity } = useWorkspace()
  const owner = identityScope(identity)
  const scope = `${owner}:${epoch}`
  const resource = assistantQuery<ReasoningSettings>(reasoningSettingsPath, owner)!
  let mutation = mutations.get(resource)
  if (!mutation) {
    mutation = new ReasoningMutation(resource, epoch)
    mutations.set(resource, mutation)
  }
  const settings = useQueryResource(resource)
  const state = useSyncExternalStore(mutation.subscribe, mutation.getSnapshot)
  useConversationRefresh(scope, () => {
    if (!mutation.getSnapshot().saving) void mutation.refresh()
  })
  return {
    options: settings.data?.options ?? [],
    selected: settings.data?.selected ?? null,
    saving: state.saving,
    ready: !!settings.data && !state.saving,
    error: settings.error || state.error,
    choose: mutation.choose,
    refresh: mutation.refresh,
    reference: (): ReasoningReference | undefined => {
      const current = resource.getSnapshot().data
      if (!current || mutation.getSnapshot().saving) return undefined
      return {
        effort: current.selected?.effort ?? null,
        preferenceRevision: current.preferenceRevision,
        configVersion: current.configVersion,
      }
    },
  }
}
